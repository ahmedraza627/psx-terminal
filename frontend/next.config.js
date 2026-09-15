/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Completely disable experimental worker flags during production build to prevent Windows access violations
  experimental: {
    webpackBuildWorker: false,
    cpus: 1, // Forces single-core thread for building, preventing OOM and segmentation faults on Windows
  },
  webpack: (config, { dev }) => {
    if (dev) {
      config.cache = false;
    }
    // Also disable webpack persistent cache in production if running on OneDrive to prevent file locks
    config.cache = false; 
    return config;
  },
};

module.exports = nextConfig;