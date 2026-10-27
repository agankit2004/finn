import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Hide the Next.js dev badge ("N" circle): it sat over the sidebar avatar and the mobile Home tab.
  devIndicators: false,
  // Lets you open the dev server from your phone on the same Wi-Fi (http://<laptop-ip>:3000).
  // Private network ranges: 192.168.x.x, 10.x.x.x and 172.16–172.31.x.x (e.g. campus Wi-Fi like 172.23.x.x).
  allowedDevOrigins: ["192.168.*.*", "10.*.*.*", "172.*.*.*"],
};

export default nextConfig;
