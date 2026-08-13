/* ===========================================================================
   Top-down floor plan — full "Plan" tab and the persistent mini-map.
   Draws the room, fixtures, and bookcase blocks; highlights active shelves.
   Same coordinate space as the room (x: 0..400 across back/front walls,
   y: 0..500 across left/right walls — y=0 is the back wall, x=0 the left wall).
   =========================================================================== */
const PLAN_BC = {
  // Meuble B — flush against the back wall, pushed to the left corner, shelves 1-12
  "bc-meubleB": { x: 10,  y: 6,   w: 120, h: 34, dir: "h" },
  // Meuble A — freestanding peninsula protruding from the left wall (left edge),
  // centered at mid-depth, shelves 13-28
  "bc-meubleA": { x: 0,   y: 230, w: 160, h: 40, dir: "h" },
};

function FloorPlan({ active, onPick, compact }) {
  const cls = "plan-svg" + (compact ? " compact" : "");
  return (
    <svg className={cls} viewBox="-6 -6 412 512" preserveAspectRatio="xMidYMid meet">
      {/* floor + walls */}
      <rect x="0" y="0" width="400" height="500" rx="3" className="pl-floor" />
      <rect x="0" y="0" width="400" height="500" rx="3" className="pl-walls" />

      {/* window, centered on the back wall (top edge) */}
      <rect x="155" y="-2" width="90" height="8" className="pl-window" />
      {/* radiator, centered directly under the window */}
      <rect x="155" y="0" width="90" height="15" className="pl-radiator" />

      {/* two workstations, one on each long face of Meuble A, both facing it,
          with a 10-unit gap off its face so the nearest shelf numbers stay visible */}
      <g className="pl-furn">
        <rect x="15" y="160" width="130" height="60" rx="2" className="pl-desk" />
        <rect x="27" y="207" width="58" height="13" rx="1" className="pl-mon" />
        <rect x="27" y="166" width="70" height="16" rx="2" className="pl-kbd" />
        <g className="pl-chair" transform="translate(80,115)">
          <rect x="-20" y="-18" width="40" height="36" rx="7" />
          <path d="M-22 18 Q-24 33 -8 36 Q8 39 22 30 Q24 22 22 18" />
        </g>

        <rect x="15" y="280" width="130" height="60" rx="2" className="pl-desk" />
        <rect x="27" y="281" width="58" height="13" rx="1" className="pl-mon" />
        <rect x="27" y="318" width="70" height="16" rx="2" className="pl-kbd" />
        <g className="pl-chair" transform="translate(80,385)">
          <rect x="-20" y="-18" width="40" height="36" rx="7" />
          <path d="M-22 18 Q-24 33 -8 36 Q8 39 22 30 Q24 22 22 18" />
        </g>
      </g>

      {/* bookcases */}
      {LIB.BOOKCASES.map((bc) => {
        const p = PLAN_BC[bc.id];
        const nums = [];
        for (let n = bc.start; n <= bc.end; n++) if (active.has(n)) nums.push(n);
        const on = nums.length > 0;
        const cx = p.x + p.w / 2, cy = p.y + p.h / 2;
        return (
          <g key={bc.id} className={"pl-bc" + (on ? " on" : "")}
             onClick={() => onPick && onPick(bc.wall, bc.start)}>
            <rect x={p.x} y={p.y} width={p.w} height={p.h} rx="2" />
            <text x={cx} y={cy} className="pl-label"
                  transform={p.dir === "v" ? `rotate(-90 ${cx} ${cy})` : ""}>
              {bc.start}–{bc.end}
            </text>
            {on && <rect x={p.x} y={p.y} width={p.w} height={p.h} rx="2" className="pl-ring" />}
          </g>
        );
      })}
    </svg>
  );
}

Object.assign(window, { FloorPlan });
