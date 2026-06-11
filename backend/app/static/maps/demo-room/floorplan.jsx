/* ===========================================================================
   Top-down floor plan — full "Plan" tab and the persistent mini-map.
   Draws the room, fixtures, and bookcase blocks; highlights active shelves.
   =========================================================================== */
const PLAN_BC = {
  "bc-4350": { x: 330, y: 6,   w: 150, h: 34, dir: "h" },
  "bc-3342": { x: 6,   y: 268, w: 34,  h: 132, dir: "v" },
  "bc-5158": { x: 560, y: 188, w: 34,  h: 100, dir: "v" },
  "bc-5966": { x: 560, y: 308, w: 34,  h: 100, dir: "v" },
  "bc-2532": { x: 6,   y: 440, w: 140, h: 34, dir: "h" },
  "bc-1724": { x: 156, y: 440, w: 140, h: 34, dir: "h" },
  "bc-0916": { x: 306, y: 440, w: 140, h: 34, dir: "h" },
  "bc-0108": { x: 456, y: 440, w: 140, h: 34, dir: "h" },
};

function FloorPlan({ active, onPick, compact }) {
  const cls = "plan-svg" + (compact ? " compact" : "");
  return (
    <svg className={cls} viewBox="-6 -6 612 492" preserveAspectRatio="xMidYMid meet">
      {/* floor + walls */}
      <rect x="0" y="0" width="600" height="480" rx="3" className="pl-floor" />
      <rect x="0" y="0" width="600" height="480" rx="3" className="pl-walls" />

      {/* window + radiator (east) */}
      <rect x="-2" y="10" width="8" height="250" className="pl-window" />
      <rect x="8" y="12" width="17" height="246" className="pl-radiator" />
      {/* door (west) */}
      <rect x="594" y="10" width="8" height="168" className="pl-door" />

      {/* desk cluster (north-east) */}
      <g className="pl-furn">
        <rect x="36" y="4" width="290" height="88" rx="2" className="pl-desk" />
        {/* desktop station */}
        <rect x="46" y="8" width="66" height="46" rx="1" className="pl-pc" />
        <rect x="50" y="60" width="60" height="16" rx="2" className="pl-kbd" />
        {/* a monitor station */}
        <rect x="146" y="9" width="66" height="13" rx="1" className="pl-mon" />
        <rect x="216" y="9" width="66" height="13" rx="1" className="pl-mon" />
        <rect x="152" y="58" width="106" height="16" rx="2" className="pl-kbd" />
        <g className="pl-chair" transform="translate(185,118)">
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
