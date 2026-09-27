import type { Metadata } from "next";
import { Karla, Vollkorn } from "next/font/google";
import "./globals.css";
import { HangerMenu } from "@/components/HangerMenu";
import { DemoResetShortcut } from "@/components/DemoResetShortcut";

const karla = Karla({ variable: "--font-karla", subsets: ["latin"], weight: ["400", "500", "600", "700"] });
const vollkorn = Vollkorn({ variable: "--font-vollkorn", subsets: ["latin"], style: ["normal", "italic"], weight: ["400", "500"] });

export const metadata: Metadata = {
  title: "Atelier",
  description: "An editorial wardrobe and stylist.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" translate="no" className={`${karla.variable} ${vollkorn.variable}`}>
      <body>
        <HangerMenu />
        <DemoResetShortcut />
        {children}
      </body>
    </html>
  );
}
