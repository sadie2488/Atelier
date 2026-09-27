"use client";

import { useRouter } from "next/navigation";
import { getStoredAvatar } from "@/lib/api";
import { Wardrobe } from "@/components/Wardrobe";

// Wardrobe intro. To remove it: delete components/Wardrobe.tsx + Wardrobe.module.css and put back
// <main className="blank-home"><button type="button" className="home-enter" onClick={...}>enter...</button></main>
export default function Home() {
  const router = useRouter();
  return (
    <main aria-label="Home">
      <Wardrobe room="dim-black" onEnter={() => router.push(getStoredAvatar() ? "/closet" : "/scan")} />
    </main>
  );
}
