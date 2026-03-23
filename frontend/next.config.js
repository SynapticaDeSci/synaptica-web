const path = require('path')

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_BACKEND_URL: process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000',
  },
  webpack: (config, { isServer }) => {
    // Stub out optional dependencies that aren't needed in browser/Next.js builds
    // pino-pretty is an optional dev dependency for pino logging
    
    // Use alias to redirect to stub modules (use absolute paths)
    config.resolve.alias = {
      ...config.resolve.alias,
      'pino-pretty': path.resolve(__dirname, 'webpack-stubs/pino-pretty.js'),
    }

    // Also add fallbacks for good measure
    config.resolve.fallback = {
      ...config.resolve.fallback,
      'pino-pretty': false,
    }

    return config
  },
}

module.exports = nextConfig
