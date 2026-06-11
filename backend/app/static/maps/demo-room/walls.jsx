/* ===========================================================================
   Flat wall elevations — a head-on view of each wall with its fixtures.
   Same Bookcase component, same coordinate space as the 3D view.
   =========================================================================== */
const WALL_ORDER = ["back", "left", "right", "front"];

function WallFixtures({ kind }) {
  if (kind === "left") {
    return (
      <React.Fragment>
        <div className="el-window" style={{ left: 10, bottom: 96, width: 240, height: 150 }}>
          <span /><span /><span /><span />
          <em className="el-sill" />
        </div>
        <div className="el-radiator" style={{ left: 18, bottom: 8, width: 224, height: 74 }}>
          {[...Array(14)].map((_, i) => <i key={i} />)}
        </div>
      </React.Fragment>
    );
  }
  if (kind === "right") {
    return (
      <div className="el-door" style={{ left: 12, bottom: 0, width: 150, height: 236 }}>
        <span className="panel p1" /><span className="panel p2" />
        <span className="el-knob" />
      </div>
    );
  }
  if (kind === "back") {
    return (
      <div className="el-desk" style={{ left: 30, bottom: 0, width: 290 }}>
        {/* LEFT — a desktop computer: base unit, colour monitor on top, keyboard */}
        <div className="el-computer-mon" style={{ left: 14, bottom: 118, width: 58, height: 46 }} />
        <div className="el-computer" style={{ left: 10, bottom: 92, width: 66, height: 26 }}>
          <i className="d1" /><i className="d2" />
        </div>
        <div className="el-computer-kbd" style={{ left: 12, bottom: 84, width: 62, height: 7 }} />
        {/* RIGHT — dual monitor display setup + keyboard */}
        <div className="el-panel" style={{ left: 124, bottom: 100, width: 62, height: 44 }}><i /></div>
        <div className="el-panel" style={{ left: 192, bottom: 100, width: 62, height: 44 }}><i /></div>
        <div className="el-kbd" style={{ left: 130, bottom: 84, width: 110, height: 7 }} />
        {/* desk body */}
        <div className="el-desktop" />
        <div className="el-leg" style={{ left: 14 }} />
        <div className="el-leg" style={{ right: 14 }} />
        {/* chair in front */}
        <div className="el-chair" style={{ left: 126 }}>
          <span className="back" /><span className="seat" /><span className="post" /><span className="foot" />
        </div>
      </div>
    );
  }
  return null;
}

function WallElevation({ active, wall, setWall }) {
  const planW = (wall === "left" || wall === "right") ? LIB.ROOM.D : LIB.ROOM.W;
  const cases = LIB.BOOKCASES.filter((b) => b.wall === wall);

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
          </div>
          <div className="elev-floor" />
        </div>
      </div>

      <div className="elev-caption">{LIB.WALL_LABEL[wall]}</div>
    </div>
  );
}

Object.assign(window, { WallElevation, WALL_ORDER });
