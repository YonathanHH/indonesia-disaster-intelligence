import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BMKG Intelligence · Indonesia hazard watch",
  description:
    "A working console for BMKG hazard intelligence: earthquakes, severe weather, tsunami potential, volcanoes and plate boundaries, ranked by an explainable priority score.",
  icons: { icon: "data:," },
};

export const viewport: Viewport = {
  themeColor: "#171719",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
