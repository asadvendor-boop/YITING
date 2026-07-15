import "./globals.css";

export const metadata = {
  title: "YITING — Evidence-Bound Incident Council",
  description: "A Qwen-powered incident command workspace with hash-chained evidence and human-governed execution.",
  metadataBase: new URL("https://yiting.47.84.232.193.sslip.io"),
  openGraph: {
    type: "website",
    title: "YITING — Evidence-Bound Incident Council",
    description: "Six Qwen-backed agents, one verified incident room: sealed evidence, human authority, measured collaboration.",
    images: ["/dashboard/brand/yiting-icon-512.png"],
  },
  twitter: { card: "summary" },
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "dark",
  themeColor: "#07111e",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
