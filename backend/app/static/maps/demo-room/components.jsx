/* ===========================================================================
   Shared Bookcase + Shelf components (rendered identically in 3D & elevations)
   Coordinate space: 1 unit = 1 px of the floor-plan, so a bookcase whose
   `len` is 150 renders 150px wide everywhere. Heights are fixed (BCH).
   =========================================================================== */
const { useMemo } = React;

const BCH = 250;          // bookcase height (px)
const CAP = 12;           // top cap thickness
const PLINTH = 16;        // base plinth thickness
const SIDE = 9;           // side panel thickness
const BOARD = 5;          // shelf board thickness

// ---- a single shelf (one numbered cell) -----------------------------------
function Shelf({ num, len, cellH, active, dim }) {
  const innerW = len - SIDE * 2;
  const bookArea = cellH - BOARD;
  const list = useMemo(() => LIB.books(num, innerW), [num, innerW]);

  return (
    <div className={"shelf" + (active ? " is-active" : "") + (dim ? " is-dim" : "")}
         style={{ height: cellH }}>
      <div className="shelf-books" style={{ height: bookArea }}>
        {list.map((b, i) => (
          <span key={i} className={"spine" + (b.bands ? " banded" : "")}
                style={{
                  width: b.w,
                  height: (b.h * bookArea) + "px",
                  background: b.color,
                  transform: b.lean ? `rotate(${b.lean}deg)` : undefined,
                  transformOrigin: "bottom " + (b.lean > 0 ? "left" : "right"),
                }} />
        ))}
      </div>
      <div className="shelf-board" />
      <span className="shelf-num">{num}</span>
      <span className="shelf-glow" aria-hidden="true" />
    </div>
  );
}

// ---- a full bookcase (stack of shelves in a wood frame) --------------------
function Bookcase({ bc, active, idPrefix }) {
  const cellH = (BCH - CAP - PLINTH) / bc.count;
  const anyActive = bc.start <= 0 ? false :
    [...Array(bc.count)].some((_, i) => active.has(bc.start + i));

  return (
    <div className={"bookcase" + (anyActive ? " has-active" : "")}
         id={idPrefix ? idPrefix + bc.id : undefined}
         style={{ width: bc.len, height: BCH }}>
      <div className="bc-cap" />
      <div className="bc-stack">
        {[...Array(bc.count)].map((_, i) => {
          const num = bc.start + i;
          return (
            <Shelf key={num} num={num} len={bc.len} cellH={cellH}
                   active={active.has(num)}
                   dim={anyActive && !active.has(num)} />
          );
        })}
      </div>
      <div className="bc-plinth" />
      <div className="bc-side bc-side-l" />
      <div className="bc-side bc-side-r" />
      <div className="bc-range">{bc.start}–{bc.end}</div>
    </div>
  );
}

Object.assign(window, { Bookcase, Shelf, BCH, CAP, PLINTH, SIDE, BOARD });
