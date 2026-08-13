/* ===========================================================================
   Library Map — shared data model & helpers (plain JS, attaches to window.LIB)
   =========================================================================== */
(function () {
  // ---- Room reference frame --------------------------------------------------
  // 1 unit = 1 real-world cm. Origin (0,0) = back-left corner of the room.
  // x: 0..400 (width, along back/front walls), y: 0..500 (depth, along left/right walls).
  const FX0 = 0, FY0 = 0;
  const PLAN_W = 400; // room width  (cm)
  const PLAN_D = 500; // room depth  (cm)

  // ---- Room dimensions used by the 3D scene (scene px == cm) ----------------
  const ROOM = { W: PLAN_W, D: PLAN_D, H: 250 };

  // ---- Bookcases (two real IKEA Kallax-style units) --------------------------
  // wall:   the wall a bookcase is associated with. For a flush bookcase this is
  //         literally the wall it's mounted against; for a "peninsula" mount it's
  //         the wall it protrudes FROM (kept so LIB.SHELVES[n].bc.wall still
  //         resolves to a real wall for camera-aiming / snap buttons).
  // cols/rows: grid shape. count (= cols*rows) numbered cubbies, numbered
  //         row-major (row 0 = top row, left -> right, then next row down).
  // along:  for a flush bookcase, [start,end] position along the wall (x for
  //         back/front, y for left/right). For a peninsula, [start,end] is how
  //         far it protrudes from the attach wall (x from the left wall).
  // z:      (peninsula only) depth-axis center of the unit, in room y (cm).
  // thick:  (peninsula only) physical thickness of the unit (cm).
  const BOOKCASES = [
    // Meuble B — back wall, 3 columns x 4 rows, shelves 1-12
    { id: "bc-meubleB", start: 1, end: 12, wall: "back", cols: 3, rows: 4, along: [10, 130] },
    // Meuble A — freestanding divider protruding from the left wall, mid-depth,
    // 4 columns x 4 rows, shelves 13-28
    { id: "bc-meubleA", start: 13, end: 28, wall: "left", cols: 4, rows: 4,
      mount: "peninsula", along: [0, 160], z: 250, thick: 40 },
  ];

  // Friendly wall labels (shown in the "Walls" elevation caption)
  const WALL_LABEL = {
    back:  "North wall · window, radiator & shelves 1–12",
    front: "South wall · no fixtures",
    left:  "East wall · Meuble A divider protrudes from here · shelves 13–28",
    right: "West wall · no fixtures",
  };

  BOOKCASES.forEach((bc) => {
    bc.count = bc.end - bc.start + 1;
    bc.len = Math.abs(bc.along[1] - bc.along[0]);
    bc.offset = Math.min(bc.along[0], bc.along[1]);
  });

  // ---- Shelf lookup: number -> { bc, idxFromTop, count } --------------------
  // idxFromTop doubles as the row-major linear index into a grid bookcase:
  // row = Math.floor(idxFromTop / bc.cols), col = idxFromTop % bc.cols.
  const SHELVES = {};
  BOOKCASES.forEach((bc) => {
    for (let n = bc.start; n <= bc.end; n++) {
      SHELVES[n] = { bc, idxFromTop: n - bc.start, count: bc.count };
    }
  });
  const SHELF_MIN = 1, SHELF_MAX = 28;

  // ---- Seeded RNG (mulberry32) ---------------------------------------------
  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // ---- Warm, realistic book-spine palette ----------------------------------
  const SPINES = [
    "#7a2f2a", "#8d4a2c", "#a06a35", "#b48a4e", "#caa86b",
    "#5c6b3e", "#3f5a44", "#2f4a52", "#33415c", "#5a3551",
    "#874b39", "#b5651d", "#d8c39a", "#6b5536", "#9c8550",
    "#43564a", "#704245", "#2e3a4d",
  ];
  const pick = (r, arr) => arr[Math.floor(r() * arr.length)];

  // ---- Generate a stable set of books for a shelf ---------------------------
  // widthPx = available width of the shelf interior. Returns array of book objs.
  function books(shelfNum, widthPx) {
    const r = rng(shelfNum * 9301 + 49297);
    const out = [];
    let x = 0;
    const inner = Math.max(0, widthPx - 4);
    const H = 0.9;                         // every book the SAME height — a tidy row
    while (x < inner - 6) {
      const w = 7 + Math.floor(r() * 13);  // 7–19 px spine — widths vary, heights don't
      if (x + w > inner) break;
      out.push({
        w,
        h: H,                              // uniform height
        lean: 0,                           // upright, no leaning
        color: pick(r, SPINES),
        bands: r() < 0.4,
        tilt: false,
      });
      x += w + 1.4;                        // even, consistent spacing
    }
    return out;
  }

  // ---- Parse a shelf query string -> sorted unique [numbers] ----------------
  // Accepts "42", "42,12,7", "33-36", "1-8, 50, 60-62"
  function parseShelves(str) {
    if (!str) return [];
    const set = new Set();
    String(str).split(/[,\s]+/).forEach((tok) => {
      tok = tok.trim();
      if (!tok) return;
      const m = tok.match(/^(\d+)\s*-\s*(\d+)$/);
      if (m) {
        let a = +m[1], b = +m[2];
        if (a > b) [a, b] = [b, a];
        for (let n = a; n <= b; n++) if (SHELVES[n]) set.add(n);
      } else if (/^\d+$/.test(tok)) {
        const n = +tok;
        if (SHELVES[n]) set.add(n);
      }
    });
    return [...set].sort((a, b) => a - b);
  }

  window.LIB = {
    ROOM, PLAN_W, PLAN_D, FX0, FY0,
    BOOKCASES, SHELVES, SHELF_MIN, SHELF_MAX, WALL_LABEL,
    rng, books, SPINES, parseShelves,
  };
})();
