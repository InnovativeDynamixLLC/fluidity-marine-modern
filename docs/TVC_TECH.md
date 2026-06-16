# Diligence: TVC Technical Moat

## 1. The Appendage Era vs. The Modulator Era
Traditional maritime propulsion relies on mechanical appendages (rudders, skegs, outboard props) to redirect water. This creates **parasitic drag** even when moving in a straight line.

### The Problem:
- **Mechanical Failure:** 60% of small-to-medium vessel engine failures are linked to mechanical linkage or propeller/rudder snagging.
- **Efficiency Loss:** Up to 12% energy loss due to rudder surface area.

## 2. TVC: Thrust Vector Control
Fluidity Marine utilizes a synchronized transom jet array to modulate the **boundary layer** of the hull.

### How it works:
1. **Node Synchronization:** 7 high-pressure thrust nodes are embedded at the transom.
2. **Differential Drag:** Steering is achieved not by "turning a prop" but by micro-adjusting the thrust intensity on individual nodes to increase or decrease drag at specific boundary layer coordinates.
3. **Software Control:** Yaw, pitch, and roll vectors are calculated at 100Hz, allowing for extreme precision and automated station holding.

## 3. The Horizontal Nozzle — Flat Sheet Jet Architecture

### What makes it different
Conventional jet propulsion uses circular nozzles. Each nozzle produces a discrete round jet — a column of high-velocity water that exits into the freestream. When you arrange multiple round jets in a row, you get an array of individual jets with gaps between them. Each jet creates its own wake, its own turbulence pattern, and its own interference with neighboring jets.

**Fluidity Marine's nozzles are not circular.**

Each nozzle is a **flattened Venturi** — a rectangular channel with rounded edges. Instead of a round exit producing a column of water, the exit is a wide, flat rectangle. The result is not a jet — it's a **sheet**.

### The flat sheet jet
When all 7 nozzles fire together, their individual rectangular exits merge into a **continuous flat sheet of water** that spans the entire lower transom line. Not 7 separate jets. One unified sheet.

Think of it like the difference between a showerhead (discrete streams) and a waterfall (continuous sheet). The waterfall couples more smoothly with the surface below it. The showerhead creates splashing, gaps, and turbulence.

### Why the sheet matters

**Boundary layer coupling:** A flat sheet jet has far more contact area with the hull boundary layer than the same total flow rate through 7 round jets. More contact area = more efficient momentum transfer = more steering authority per unit of pump power.

**No jet-to-jet interference:** Round jets in an array create complex interference patterns where the wakes of adjacent jets collide. These interference zones are unpredictable, create turbulence, and waste energy. A continuous sheet has no gaps, no interference zones, and no wasted energy between jets.

**Reduced turbulence signature:** A sheet jet entrains water more gradually than a round jet. The velocity gradient at the sheet edge is lower, meaning less turbulent mixing, less noise, and a smaller acoustic/thermal signature — relevant for both recreational comfort and defense applications.

**Rounded edges prevent flow separation:** The rectangular channel's rounded edges are critical. Sharp corners in a non-circular nozzle would cause flow separation — the water would detach from the wall, creating vortices and reducing efficiency. The rounded edges keep the flow attached through the transition from circular inlet to rectangular exit, maintaining the Venturi acceleration profile.

### The Venturi profile
Each nozzle follows a Venturi profile: the channel narrows from the inlet to the throat, then expands slightly toward the exit. This geometry:
- Accelerates the water smoothly (Bernoulli principle)
- Minimizes flow separation at the walls
- Maximizes exit velocity for a given pump pressure
- The flattened rectangular exit is the final stage of this acceleration

### Manufacturing advantage
The flattened Venturi geometry is well-suited to modern manufacturing:
- CNC machining from 316L stainless steel billet
- Ceramic coating for corrosion resistance and wear life
- Modular design: each nozzle is a self-contained unit
- The rectangular exit is easier to inspect and maintain than complex internal geometries

## 4. Scalability & Manufacturing
By removing complex steerable mechanical units, we utilize a **modular, 3D-printable architecture**. This allows:
- **Local Assembly:** Regional manufacturing hubs instead of centralized industrial shipyards.
- **Maintenance-Free Bottoms:** No moving parts below the waterline translates to lower ownership costs and higher reliability in harsh environments.
