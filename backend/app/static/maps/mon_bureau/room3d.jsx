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

// room-space (0..W, 0..D) -> scene-centered coords used by every 3D element
const px = (x) => x - LIB.FX0 - R.W / 2;
const pz = (y) => y - LIB.FY0 - R.D / 2;

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
// Default orientation: person faces -z (the pellicle mesh back sits at +z).
// Pass flip to mirror the whole assembly along z so the person faces +z instead
// — used so each workstation's chair faces toward Meuble A regardless of which
// side of the peninsula it's on.
function AeronChair({ cx, cz, fy, flip }) {
  const s = flip ? -1 : 1;
  const legs = [0, 72, 144, 216, 288].map((a) => {
    const ang = flip ? a + 180 : a;
    const r = (ang * Math.PI) / 180, dx = Math.sin(r), dz = Math.cos(r);
    return (
      <React.Fragment key={a}>
        <Box w={9} h={7} d={56} x={cx + dx * 28} y={fy - 5} z={cz + dz * 28} ry={ang} cls="chair-leg" />
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
      <Box w={6} h={28} d={6} x={cx - 28} y={fy - 70} z={cz - 4 * s} cls="chair-arm-post" />
      <Box w={6} h={28} d={6} x={cx + 28} y={fy - 70} z={cz - 4 * s} cls="chair-arm-post" />
      <Box w={11} h={8} d={34} x={cx - 28} y={fy - 86} z={cz - 4 * s} cls="aeron-arm" />
      <Box w={11} h={8} d={34} x={cx + 28} y={fy - 86} z={cz - 4 * s} cls="aeron-arm" />
      {/* mesh back, reclined */}
      <Box w={49} h={86} d={8} x={cx} y={fy - 106} z={cz + 25 * s} rx={-13} cls="aeron-back" />
      {/* lumbar pad */}
      <Box w={44} h={13} d={6} x={cx} y={fy - 80} z={cz + 31 * s} rx={-13} cls="aeron-lumbar" />
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
  return bc.offset; // back
}

// flush (wall-mounted) bookcases only — a "peninsula" mount is rendered
// separately by <Peninsula>, since it floats mid-room rather than sitting
// flat inside one of the four <Wall> planes.
const byWall = (wall, active) => LIB.BOOKCASES.filter((b) => b.wall === wall && b.mount !== "peninsula")
  .map((bc) => (
    <div key={bc.id} className="wall-bc" style={{ left: bcOffset(bc), bottom: 0 }}>
      <Bookcase bc={bc} active={active} idPrefix="r3-" />
    </div>
  ));

// ---- a freestanding "peninsula" bookcase protruding from a wall into the
// room (Meuble A): rendered as two back-to-back Bookcase panels, one facing
// each way, so the same 16 numbers are visible from either side of the
// room — plus a slim end-cap closing off the far (open-room) end.
function Peninsula({ bc, active }) {
  const fy = R.H / 2;
  const cx = px((bc.along[0] + bc.along[1]) / 2);
  const cy = fy - BCH / 2;
  const half = (bc.thick || 40) / 2;
  const face = (z, ry, key, mirror) => (
    <div key={key} className="wall-bc"
         style={{ width: bc.len, height: BCH, marginLeft: -bc.len / 2, marginTop: -BCH / 2,
                  transform: `translate3d(${cx}px, ${cy}px, ${z}px) rotateY(${ry}deg)` }}>
      <Bookcase bc={bc} active={active} idPrefix={"r3-pen" + key + "-"} mirror={mirror} />
    </div>
  );
  return (
    <React.Fragment>
      {face(pz(bc.z) + half, 0, "f", false)}
      {face(pz(bc.z) - half, 180, "b", true)}
      {/* end-cap at the open-room end */}
      <Box w={12} h={BCH} d={bc.thick || 40} x={px(bc.along[1]) + 6} y={cy} z={pz(bc.z)} cls="wood" />
    </React.Fragment>
  );
}

// ---- one desk + monitor + keyboard + chair, butted up against Meuble A's
// long face so the person sits facing the peninsula.
// faceZ: +1 if Meuble A is toward larger z from this desk, -1 if toward smaller z.
// (y decreases upward: floor is at fy, ceiling at -fy; "surf" below is the
// desk's TOP FACE height, so anything resting on it has bottom edge = surf)
function Workstation({ cx, cz, faceZ }) {
  const fy = R.H / 2;
  const DW = 130, DD = 60;
  const lx = DW / 2 - 12, lz = DD / 2 - 12;
  const DESK_H = 10, LEG_H = 65;
  const surf = fy - 75; // desk top surface ~75cm off the floor

  return (
    <React.Fragment>
      <Box w={DW} h={DESK_H} d={DD} x={cx} y={surf + DESK_H / 2} z={cz} cls="wood-top" />
      <Box w={8} h={LEG_H} d={8} x={cx - lx} y={fy - LEG_H / 2} z={cz - lz} cls="wood" />
      <Box w={8} h={LEG_H} d={8} x={cx + lx} y={fy - LEG_H / 2} z={cz - lz} cls="wood" />
      <Box w={8} h={LEG_H} d={8} x={cx - lx} y={fy - LEG_H / 2} z={cz + lz} cls="wood" />
      <Box w={8} h={LEG_H} d={8} x={cx + lx} y={fy - LEG_H / 2} z={cz + lz} cls="wood" />

      {/* monitor on the edge closest to Meuble A */}
      <Box w={30} h={5}  d={18} x={cx} y={surf - 2.5} z={cz + faceZ * (lz - 6)} cls="panel-stand" />
      <Box w={7}  h={22} d={7}  x={cx} y={surf - 16}   z={cz + faceZ * (lz - 6)} cls="panel-stand" />
      <Box w={56} h={36} d={7}  x={cx} y={surf - 45}   z={cz + faceZ * (lz - 4)} cls="panel" />

      {/* keyboard, on the chair side */}
      <Box w={58} h={6} d={20} x={cx} y={surf - 3} z={cz - faceZ * 8} cls="keyboard" />

      {/* chair, facing Meuble A */}
      <AeronChair cx={cx} cz={cz - faceZ * 75} fy={fy} flip={faceZ > 0} />
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

  const peninsulas = LIB.BOOKCASES.filter((b) => b.mount === "peninsula");

  return (
    <div className={"stage3 " + (inside ? "is-inside" : "is-doll")}
         style={{ perspective: (inside ? P_IN : 1500) + "px" }}
         onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp}>
      <div className="scene3" style={{ transform: sceneTf }}>
        {/* floor */}
        <div className="floor3" style={{ width: R.W, height: R.D, marginLeft: -R.W / 2, marginTop: -R.D / 2, transform: `translateY(${R.H / 2}px) rotateX(90deg)` }} />
        {/* ceiling (inside only) */}
        {inside && <div className="ceil3" style={{ width: R.W, height: R.D, marginLeft: -R.W / 2, marginTop: -R.D / 2, transform: `translateY(${-R.H / 2}px) rotateX(90deg)` }} />}
        <div className="rug3" style={{ width: 220, height: 220, marginLeft: -110, marginTop: -110, transform: `translate3d(60px, ${R.H / 2 - 1}px, 0px) rotateX(90deg)` }} />

        <Wall kind="back" w={R.W} h={R.H} hidden={hidden === "back"} transform={`translateZ(${-R.D / 2}px)`}>
          {byWall("back", active)}
          {/* window centered on the back wall */}
          <div className="window3" style={{ left: 155, top: 45, width: 90, height: 110 }}>
            <span /><span /><span /><span />
          </div>
        </Wall>
        {/* radiator, centered on the back wall directly under the window */}
        <Box w={90} h={90} d={15} x={px(200)} y={R.H / 2 - 45} z={-R.D / 2 + 7.5} cls="radiator" />
        <Wall kind="front" w={R.W} h={R.H} hidden={hidden === "front"} transform={`translateZ(${R.D / 2}px) rotateY(180deg)`}>
          {byWall("front", active)}
        </Wall>
        <Wall kind="left" w={R.D} h={R.H} hidden={hidden === "left"} transform={`translateX(${-R.W / 2}px) rotateY(90deg)`}>
          {byWall("left", active)}
        </Wall>
        <Wall kind="right" w={R.D} h={R.H} hidden={hidden === "right"} transform={`translateX(${R.W / 2}px) rotateY(-90deg)`}>
          {byWall("right", active)}
        </Wall>

        {peninsulas.map((bc) => <Peninsula key={bc.id} bc={bc} active={active} />)}

        {/* two workstations, one on each long face of Meuble A, both facing it,
            with a 10-unit gap off its face so the nearest shelf numbers stay visible */}
        <Workstation cx={px(80)} cz={-60} faceZ={1} />
        <Workstation cx={px(80)} cz={60} faceZ={-1} />
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
