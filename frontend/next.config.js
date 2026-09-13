/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    // Compile in-process instead of a separate build worker - avoids OOM
    // crashes on memory-constrained dev machines. No effect on output.
    webpackBuildWorker: false,
  },
  webpack: (config, { dev }) => {
    if (dev) {
      // Disable webpack's persistent filesystem cache in development.
      // The .pack/.pack.gz cache files under .next/cache live on OneDrive,
      // which holds exclusive locks and evicts files on sync - producing
      // "ENOENT ... stat ...0.pack.gz" build-cache crashes. Disabling the
      // persistent cache trades a slower warm start for a stable dev loop.
      config.cache = false;
    }
    return config;
  },
};

module.exports = nextConfig;
