import type { NextConfig } from "next";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// __dirname is unreliable in Next's TS/ESM config loader. Compute the
// frontend directory explicitly so Turbopack pins its workspace root here
// regardless of the CWD that launched `next dev`.
const here =
  typeof __dirname !== "undefined"
    ? __dirname
    : dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  turbopack: {
    root: resolve(here),
  },
};

export default nextConfig;