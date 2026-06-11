/* ===========================================================================
   3D room with TWO cameras:
   - "inside": first-person. Eye sits at room-centre; drag to look around.
     The wall behind you falls outside the view frustum, so it's never drawn.
   - "doll":   the original outside-in dollhouse orbit.
   =========================================================================== */
const { useState: use3, useRef: ref3, useEffect: eff3 } = React;
const R = LIB.ROOM; // {W,D,H}
const P_IN = 560;     // inside perspective
const STAND = 210;    // how far the eye stands in front of room-centre
const EYE_LIFT = 26;  // raise the eye toward standing height

// ---- shaded cuboid (per-face classes + optional rotation + CSS textures) ---
function Box({ w, h, d, x, y, z, tone, cls = "", ry = 0, rx = 0 }) {
  const face = (name, fw, fh, tf, br) => (
    <i className={"bx " + name} style={{
      width: fw, height: fh, marginLeft: -fw / 2, marginTop: -fh / 2, transform: tf,
      background: tone || undefined, filter: br ? `brightness(${br})` : undefined,
    }} />
  );
  return (
    <div className={"box " + cls}
         style={{ transform: `translate3d(${x}px,${y}px,${z}px) rotateY(${ry}deg) rotateX(${rx}deg)` }}>
      {face("front", w, h, `translateZ(${d / 2}px)`)}
      {face("back",  w, h, `rotateY(180deg) translateZ(${d / 2}px)`, 0.8)}
      {face("right", d, h, `rotateY(90deg) translateZ(${w / 2}px)`, 0.9)}
      {face("left",  d, h, `rotateY(-90deg) translateZ(${w / 2}px)`, 0.72)}
      {face("top",   w, d, `rotateX(90deg) translateZ(${h / 2}px)`, 1.12)}
    </div>
  );
}

// ---- Herman Miller Aeron-style mesh chair -----------------------------------
// Person faces the desk (north / −z); the pellicle mesh back faces +z (toward
// the room), so you see the mesh when looking at the north wall.
function AeronChair({ cx, cz, fy }) {
  const legs = [0, 72, 144, 216, 288].map((a) => {
    const r = (a * Math.PI) / 180, dx = Math.sin(r), dz = Math.cos(r);
    return (
      <React.Fragment key={a}>
        <Box w={9} h={7} d={56} x={cx + dx * 28} y={fy - 5} z={cz + dz * 28} ry={a} cls="chair-leg" />
        <Box w={13} h={13} d={13} x={cx + dx * 55} y={fy - 8} z={cz + dz * 55} cls="caster" />
      </React.Fragment>
    );
  });
  return (
    <React.Fragment>
      {legs}
      {/* gas-lift post */}
      <Box w={14} h={48} d={14} x={cx} y={fy - 27} z={cz} cls="chair-post" />
      {/* seat pan */}
      <Box w={52} h={12} d={50} x={cx} y={fy - 56} z={cz} cls="aeron-seat" />
      {/* arm posts + pads */}
      <Box w={6} h={28} d={6} x={cx - 28} y={fy - 70} z={cz - 4} cls="chair-arm-post" />
      <Box w={6} h={28} d={6} x={cx + 28} y={fy - 70} z={cz - 4} cls="chair-arm-post" />
      <Box w={11} h={8} d={34} x={cx - 28} y={fy - 86} z={cz - 4} cls="aeron-arm" />
      <Box w={11} h={8} d={34} x={cx + 28} y={fy - 86} z={cz - 4} cls="aeron-arm" />
      {/* mesh back, reclined */}
      <Box w={49} h={86} d={8} x={cx} y={fy - 106} z={cz + 25} rx={-13} cls="aeron-back" />
      {/* lumbar pad */}
      <Box w={44} h={13} d={6} x={cx} y={fy - 80} z={cz + 31} rx={-13} cls="aeron-lumbar" />
    </React.Fragment>
  );
}

function Wall({ kind, transform, w, h, hidden, children }) {
  return (
    <div className={"wall3 wall-" + kind + (hidden ? " behind" : "")}
         style={{ width: w, height: h, marginLeft: -w / 2, marginTop: -h / 2, transform }}>
      {children}
    </div>
  );
}

function bcOffset(bc) {
  if (bc.wall === "left")  return (R.D - bc.offset - bc.len);
  if (bc.wall === "right") return bc.offset;
  if (bc.wall === "front") return (R.W - bc.offset - bc.len);
  return bc.offset;
}

const byWall = (wall, active) => LIB.BOOKCASES.filter((b) => b.wall === wall)
  .map((bc) => (
    <div key={bc.id} className="wall-bc" style={{ left: bcOffset(bc), bottom: 0 }}>
      <Bookcase bc={bc} active={active} idPrefix="r3-" />
    </div>
  ));

function Furniture() {
  const fy = R.H / 2;
  const px = (x) => x - LIB.FX0 - R.W / 2;
  const pz = (y) => y - LIB.FY0 - R.D / 2;
  const deskCx = px((100 + 370) / 2), deskCz = pz((54 + 145) / 2);
  const surf = fy - 99;        // desk top surface (y; smaller = higher)
  const DW = 280, DD = 96;     // desk top size
  const lx = DW / 2 - 16, lz = DD / 2 - 16;  // leg inset

  // dual monitor monitor (stand base + neck + screen)
  const Panel = ({ ox, ry }) => (
    <React.Fragment>
      <Box w={30} h={5}  d={18} x={deskCx + ox} y={surf - 2.5} z={deskCz - 14} cls="panel-stand" />
      <Box w={7}  h={26} d={7}  x={deskCx + ox} y={surf - 18}  z={deskCz - 14} cls="panel-stand" />
      <Box w={66} h={44} d={8}  x={deskCx + ox} y={fy - 148}   z={deskCz - 12} ry={ry} cls="panel" />
    </React.Fragment>
  );

  return (
    <React.Fragment>
      {/* old cast-iron column radiator — east wall, north end, on little feet */}
      <Box w={22} h={112} d={150} x={-R.W / 2 + 15} y={fy - 58} z={pz((62 + 298) / 2)} cls="radiator" />

      {/* DESK — top slab, four legs (clear knee space), slim modesty panel at the back */}
      <Box w={DW} h={14} d={DD} x={deskCx} y={fy - 92} z={deskCz} cls="wood-top" />
      <Box w={11} h={84} d={11} x={deskCx - lx} y={fy - 43} z={deskCz - lz} cls="wood" />
      <Box w={11} h={84} d={11} x={deskCx + lx} y={fy - 43} z={deskCz - lz} cls="wood" />
      <Box w={11} h={84} d={11} x={deskCx - lx} y={fy - 43} z={deskCz + lz} cls="wood" />
      <Box w={11} h={84} d={11} x={deskCx + lx} y={fy - 43} z={deskCz + lz} cls="wood" />
      <Box w={DW - 26} h={26} d={5} x={deskCx} y={fy - 80} z={deskCz - (DD / 2 - 4)} cls="wood" />

      {/* LEFT STATION — a desktop computer: base unit + colour monitor on top + keyboard */}
      <Box w={84} h={24} d={58} x={deskCx - 86} y={surf - 12} z={deskCz - 12} cls="computer" />
      <Box w={66} h={52} d={54} x={deskCx - 86} y={fy - 149} z={deskCz - 14} cls="computer-mon" />
      <Box w={74} h={7}  d={26} x={deskCx - 86} y={surf - 3.5} z={deskCz + 30} cls="computer-kbd" />

      {/* RIGHT STATION — dual monitor display setup, toed in, with its keyboard */}
      <Panel ox={28} ry={11} />
      <Panel ox={96} ry={-11} />
      <Box w={104} h={7} d={28} x={deskCx + 62} y={surf - 3.5} z={deskCz + 30} cls="keyboard" />

      {/* the Aeron */}
      <AeronChair cx={deskCx} cz={deskCz + 104} fy={fy} />
    </React.Fragment>
  );
}

// which wall is directly behind the camera in inside-mode (so we can drop it)
const DIR_WALL = ["back", "right", "front", "left"]; // index = facing direction
function behindWall(yaw) {
  const dir = (((Math.round(yaw / 90) % 4) + 4) % 4);
  return DIR_WALL[(dir + 2) % 4];
}

function Room3D({ active, face, mode, setMode }) {
  // yaw / pitch are shared; their meaning differs per camera
  const DEFAULTS = { inside: { yaw: -10, pitch: 0 }, doll: { yaw: -32, pitch: 16 } };
  const [yaw, setYaw] = use3(DEFAULTS.inside.yaw);
  const [pitch, setPitch] = use3(DEFAULTS.inside.pitch);
  const drag = ref3(null);
  const modeRef = ref3(mode);
  modeRef.current = mode;

  // aim at a wall on request (snap straight to it; drag gives smooth look-around)
  eff3(() => {
    if (!face || !face.wall) return;
    if (modeRef.current === "inside") {
      const m = { back: 0, right: 90, front: 180, left: -90 };
      setYaw(m[face.wall] ?? 0); setPitch(-4);
    } else {
      const m = { back: 0, right: -90, front: 180, left: 90 };
      setYaw(m[face.wall] ?? 0); setPitch(14);
    }
  }, [face]);

  const onDown = (e) => { drag.current = { x: e.clientX, y: e.clientY, yaw, pitch }; };
  const onMove = (e) => {
    if (!drag.current) return;
    const d = drag.current, dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (mode === "inside") {
      setYaw(d.yaw - dx * 0.2);
      setPitch(Math.max(-24, Math.min(20, d.pitch + dy * 0.16)));
    } else {
      setYaw(d.yaw + dx * 0.4);
      setPitch(Math.max(2, Math.min(46, d.pitch - dy * 0.25)));
    }
  };
  const onUp = () => { drag.current = null; };

  const toggle = (m) => {
    if (m === mode) return;
    setMode(m); setYaw(DEFAULTS[m].yaw); setPitch(DEFAULTS[m].pitch);
  };

  const inside = mode === "inside";
  const sceneTf = inside
    ? `translateZ(${P_IN - STAND}px) translateY(${EYE_LIFT}px) rotateX(${pitch}deg) rotateY(${yaw}deg)`
    : `translateZ(-560px) rotateX(${pitch}deg) rotateY(${yaw}deg)`;
  const hidden = inside ? behindWall(yaw) : null;

  return (
    <div className={"stage3 " + (inside ? "is-inside" : "is-doll")}
         style={{ perspective: (inside ? P_IN : 1500) + "px" }}
         onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp}>
      <div className="scene3" style={{ transform: sceneTf }}>
        {/* floor */}
        <div className="floor3" style={{ width: R.W, height: R.D, marginLeft: -R.W / 2, marginTop: -R.D / 2, transform: `translateY(${R.H / 2}px) rotateX(90deg)` }} />
        {/* ceiling (inside only) */}
        {inside && <div className="ceil3" style={{ width: R.W, height: R.D, marginLeft: -R.W / 2, marginTop: -R.D / 2, transform: `translateY(${-R.H / 2}px) rotateX(90deg)` }} />}
        <div className="rug3" style={{ width: 250, height: 250, marginLeft: -125, marginTop: -125, transform: `translateY(${R.H / 2 - 1}px) rotateX(90deg)` }} />

        <Wall kind="back" w={R.W} h={R.H} hidden={hidden === "back"} transform={`translateZ(${-R.D / 2}px)`}>
          {byWall("back", active)}
        </Wall>
        <Wall kind="front" w={R.W} h={R.H} hidden={hidden === "front"} transform={`translateZ(${R.D / 2}px) rotateY(180deg)`}>
          {byWall("front", active)}
        </Wall>
        <Wall kind="left" w={R.D} h={R.H} hidden={hidden === "left"} transform={`translateX(${-R.W / 2}px) rotateY(90deg)`}>
          {byWall("left", active)}
          {/* window sits at the north end of the wall, above the radiator */}
          <div className="window3" style={{ left: 264, top: 30, width: 176, height: 150 }}>
            <span /><span /><span /><span />
          </div>
        </Wall>
        <Wall kind="right" w={R.D} h={R.H} hidden={hidden === "right"} transform={`translateX(${R.W / 2}px) rotateY(-90deg)`}>
          {byWall("right", active)}
          <div className="door3" style={{ left: 8, bottom: 0, width: 96, height: 232 }}>
            <span className="knob" />
          </div>
        </Wall>

        <Furniture />
      </div>

      {/* camera toggle */}
      <div className="cam-toggle">
        <button className={inside ? "on" : ""} onClick={() => toggle("inside")}>Inside</button>
        <button className={!inside ? "on" : ""} onClick={() => toggle("doll")}>Dollhouse</button>
      </div>
      <div className="hint3">{inside ? "drag to look around" : "drag to orbit"}</div>
    </div>
  );
}

Object.assign(window, { Room3D });
