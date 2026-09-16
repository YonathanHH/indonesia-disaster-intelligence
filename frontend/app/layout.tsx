import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BMKG Intelligence — Indonesia Environmental Intelligence",
  description:
    "Real-time geospatial intelligence console for Indonesia using BMKG authoritative data.",
  icons: { icon: "data:," },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
