/* ===========================================================================
   Library Map — shared data model & helpers (plain JS, attaches to window.LIB)
   =========================================================================== */
(function () {
  // ---- Floor-plan reference frame (from the original SVG) -------------------
  // x: 60..660 (width 600), y: 50..530 (depth 480)
  const FX0 = 60, FX1 = 660, FY0 = 50, FY1 = 530;
  const PLAN_W = FX1 - FX0; // 600
  const PLAN_D = FY1 - FY0; // 480

  // ---- Room dimensions used by the 3D scene (scene px) ----------------------
  const ROOM = { W: PLAN_W, D: PLAN_D, H: 330 };

  // ---- Bookcases ------------------------------------------------------------
  // wall: which wall it sits on.
  // along: [start,end] in floor-plan coordinates (x for back/front, y for left/right).
  // The number of shelves equals the size of the number range.
  const BOOKCASES = [
    { id: "bc-4350", start: 43, end: 50, wall: "back",  along: [390, 540] },
    { id: "bc-3342", start: 33, end: 42, wall: "left",  along: [320, 450] },
    { id: "bc-5158", start: 51, end: 58, wall: "right", along: [240, 340] },
    { id: "bc-5966", start: 59, end: 66, wall: "right", along: [360, 460] },
    { id: "bc-2532", start: 25, end: 32, wall: "front", along: [64, 204] },
    { id: "bc-1724", start: 17, end: 24, wall: "front", along: [214, 354] },
    { id: "bc-0916", start: 9,  end: 16, wall: "front", along: [364, 504] },
    { id: "bc-0108", start: 1,  end: 8,  wall: "front", along: [514, 654] },
  ];

  // Friendly wall labels
  const WALL_LABEL = {
    back:  "North wall · desk & shelves 43–50",
    front: "South wall · shelves 1–32",
    left:  "West wall · window & shelves 33–42",
    right: "East wall · door & shelves 51–66",
  };

  BOOKCASES.forEach((bc) => {
    bc.count = bc.end - bc.start + 1;
    bc.len = Math.abs(bc.along[1] - bc.along[0]);
    bc.offset = Math.min(bc.along[0], bc.along[1]) - (bc.wall === "left" || bc.wall === "right" ? FY0 : FX0);
  });

  // ---- Shelf lookup: number -> { bc, idxFromTop, count } --------------------
  const SHELVES = {};
  BOOKCASES.forEach((bc) => {
    for (let n = bc.start; n <= bc.end; n++) {
      SHELVES[n] = { bc, idxFromTop: n - bc.start, count: bc.count };
    }
  });
  const SHELF_MIN = 1, SHELF_MAX = 66;

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
