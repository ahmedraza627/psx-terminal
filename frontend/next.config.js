/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: false,
  webpack: function (config) {
    // Reduce memory pressure on constrained builds
    if (config.optimization && config.optimization.splitChunks) {
      config.optimization.splitChunks.maxAsyncRequests = 1;
      config.optimization.splitChunks.maxInitialRequests = 1;
    }
    return config;
  },
};
