import type { NextConfig } from "next";
import { withEve } from "eve/next";

// Run the Next.js frontend and the eve agent (./agent) as one project. withEve
// mounts the eve routes (/eve/v1/*) same-origin, so useEveAgent needs no host or
// CORS config. See node_modules/eve/docs/guides/frontend/nextjs.mdx.
const nextConfig: NextConfig = {};

export default withEve(nextConfig);
