# Fluidity Marine

**The Operating System of the Water.**

Thrust Vector Control (TVC) — a rudderless marine propulsion system that replaces mechanical appendages with a synchronized array of software-defined thrust nodes.

## Tech Stack

- **Astro 6** — Static site generation
- **Pure CSS** — No framework dependencies, maximum build stability
- **GitHub Actions** — CI/CD via Ubuntu runners (local macOS 11 build incompatible with esbuild v6)

## Pages

| Route | Content |
|-------|---------|
| `/` | Home — Hero, particle animation, campaign alert |
| `/technology` | TVC deep dive, technical specs, comparison |
| `/about` | Company narrative, mission, The Floating Bar |
| `/investors` | Seed round pitch, thesis, roadmap |
| `/press` | Media kit, brand assets, narrative brief |

## Development

```bash
npm install
npm run dev     # Astro dev server
npm run build   # Production build → dist/
```

## Deployment

Push to `master` → GitHub Actions builds on Ubuntu (Node 22) → rsync to Dreamhost shared hosting.
