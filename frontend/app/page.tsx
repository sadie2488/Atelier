"use client";

import { useRouter } from "next/navigation";
import { getStoredAvatar } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  return (
    <main className="blank-home" aria-label="Home">
      <button type="button" className="home-enter" onClick={() => router.push(getStoredAvatar() ? "/closet" : "/scan")}>enter...</button>
    </main>
  );
}
