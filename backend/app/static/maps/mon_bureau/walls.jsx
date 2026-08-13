/* ===========================================================================
   Flat wall elevations — a head-on view of each wall with its fixtures.
   Same Bookcase component, same coordinate space as the 3D view.
   =========================================================================== */
const WALL_ORDER = ["back", "left", "right", "front"];

function WallFixtures({ kind }) {
  if (kind === "back") {
    return (
      <React.Fragment>
        <div className="el-window" style={{ left: 155, bottom: 95, width: 90, height: 110 }}>
          <span /><span /><span />
          <em className="el-sill" />
        </div>
        {/* radiator, centered directly under the window */}
        <div className="el-radiator" style={{ left: 155, bottom: 8, width: 90, height: 74 }}>
          {[...Array(6)].map((_, i) => <i key={i} />)}
        </div>
      </React.Fragment>
    );
  }
  // left/right/front walls carry no flush fixtures — Meuble A (left) is a
  // freestanding peninsula, shown below as a schematic card instead.
  return null;
}

function WallElevation({ active, wall, setWall }) {
  const planW = (wall === "left" || wall === "right") ? LIB.ROOM.D : LIB.ROOM.W;
  const cases = LIB.BOOKCASES.filter((b) => b.wall === wall && b.mount !== "peninsula");
  const peninsula = wall === "left"
    ? LIB.BOOKCASES.find((b) => b.wall === wall && b.mount === "peninsula")
    : null;
  const penActive = peninsula && [...Array(peninsula.count)].some((_, i) => active.has(peninsula.start + i));

  const offset = (bc) => bc.offset; // local left along the wall

  return (
    <div className="elev-wrap">
      <div className="elev-tabs">
        {WALL_ORDER.map((k) => (
          <button key={k} className={"elev-tab" + (k === wall ? " on" : "")} onClick={() => setWall(k)}>
            <span className="dot" data-w={k} />
            {k === "back" ? "North" : k === "front" ? "South" : k === "left" ? "East" : "West"}
          </button>
        ))}
      </div>

      <div className="elev-stage">
        <div className="elev-room" style={{ width: planW, height: LIB.ROOM.H + 54 }}>
          <div className="elev-wall" style={{ width: planW, height: LIB.ROOM.H }}>
            <WallFixtures kind={wall} />
            {cases.map((bc) => (
              <div key={bc.id} className="elev-bc" style={{ left: offset(bc), bottom: 0 }}>
                <Bookcase bc={bc} active={active} idPrefix="el-" />
              </div>
            ))}
            {peninsula && (
              <div className={"elev-peninsula" + (penActive ? " on" : "")}
                   style={{ left: peninsula.z - (peninsula.thick || 40) / 2,
                            width: peninsula.thick || 40, height: BCH }}>
                {peninsula.start}–{peninsula.end}<br />freestanding — see Room view
              </div>
            )}
          </div>
          <div className="elev-floor" />
        </div>
      </div>

      <div className="elev-caption">{LIB.WALL_LABEL[wall]}</div>
    </div>
  );
}

Object.assign(window, { WallElevation, WALL_ORDER });
