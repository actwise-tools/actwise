import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ActWise — NICE Actimize Documentation",
  description:
    "Ask NICE Actimize product documentation questions with your own DOCenter account.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
