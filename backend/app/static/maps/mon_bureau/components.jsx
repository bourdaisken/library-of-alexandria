/* ===========================================================================
   Shared Bookcase + Shelf components (rendered identically in 3D & elevations)
   Coordinate space: 1 unit = 1 px of the room (== 1 cm), so a bookcase whose
   `len` is 150 renders 150px wide everywhere. Heights are fixed (BCH).

   A bookcase can be a single column (bc.cols undefined/1, one shelf spans the
   full width, stacked vertically — the original layout) or a grid (bc.cols>1,
   bc.rows rows of bc.cols cubbies each, numbered row-major: row 0 = top row,
   left -> right, then the next row down). Either way every numbered cell is
   still a plain <Shelf num=...> using the same active/dim highlight classes.
   =========================================================================== */
const { useMemo } = React;

const BCH = 160;          // bookcase height (px) — fits a 4-row Kallax under a 250px ceiling
const CAP = 8;             // top cap thickness
const PLINTH = 10;         // base plinth thickness
const SIDE = 6;             // side panel thickness
const BOARD = 4;            // shelf board thickness

// ---- a single shelf / cubby (one numbered cell) ----------------------------
function Shelf({ num, len, cellH, active, dim, sidePad = SIDE, gridWidth, tight }) {
  const innerW = len - sidePad * 2;
  const bookArea = cellH - BOARD;
  const list = useMemo(() => LIB.books(num, innerW), [num, innerW]);

  return (
    <div className={"shelf" + (active ? " is-active" : "") + (dim ? " is-dim" : "")}
         style={{ height: cellH, width: gridWidth }}>
      <div className={"shelf-books" + (tight ? " tight" : "")} style={{ height: bookArea }}>
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

// ---- a full bookcase (grid or single-column stack, in a wood frame) --------
// mirror: when this same bookcase is rendered a second time as the flipped
// (rotateY 180) back face of a freestanding peninsula, the rotation itself
// already mirrors left<->right — so pass mirror to pre-reverse the column
// draw order, which cancels that flip and keeps the numbering reading the
// same way (left-to-right increasing) from either side. Rows are untouched
// since a Y-axis rotation never affects vertical order.
function Bookcase({ bc, active, idPrefix, mirror }) {
  const cols = bc.cols || 1;
  const rows = bc.rows || bc.count;
  const cellH = (BCH - CAP - PLINTH) / rows;
  const cellW = cols > 1 ? (bc.len - SIDE * 2) / cols : bc.len;
  const anyActive = [...Array(bc.count)].some((_, i) => active.has(bc.start + i));

  return (
    <div className={"bookcase" + (anyActive ? " has-active" : "")}
         id={idPrefix ? idPrefix + bc.id : undefined}
         style={{ width: bc.len, height: BCH }}>
      <div className="bc-cap" />
      <div className="bc-stack">
        {[...Array(rows)].map((_, r) => (
          <div className="bc-row" key={r} style={{ height: cellH }}>
            {[...Array(cols)].map((_, c) => {
              const col = mirror ? cols - 1 - c : c;
              const num = bc.start + r * cols + col;
              return (
                <Shelf key={num} num={num} len={cellW} cellH={cellH}
                       sidePad={cols > 1 ? 0 : SIDE}
                       gridWidth={cellW} tight={cols > 1}
                       active={active.has(num)}
                       dim={anyActive && !active.has(num)} />
              );
            })}
          </div>
        ))}
      </div>
      <div className="bc-plinth" />
      <div className="bc-side bc-side-l" />
      <div className="bc-side bc-side-r" />
      <div className="bc-range">{bc.start}–{bc.end}</div>
    </div>
  );
}

Object.assign(window, { Bookcase, Shelf, BCH, CAP, PLINTH, SIDE, BOARD });
