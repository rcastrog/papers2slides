import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "paper2slides",
  description: "Minimal UI for paper processing runs",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
