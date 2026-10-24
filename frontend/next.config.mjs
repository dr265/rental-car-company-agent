/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Static export: the FastAPI backend serves ./out as static files at /ui
  // (and /) so no Node server is needed at runtime. All API calls go to
  // http://localhost:8022 (NEXT_PUBLIC_API_URL).
  output: "export",
  images: { unoptimized: true },
  // Emit <route>/index.html for every page (console/index.html) so the
  // backend's StaticFiles(html=True) mount resolves /console correctly.
  trailingSlash: true,
  // next dev keeps live reloading in development; the export only affects `next build`.
};

export default nextConfig;
