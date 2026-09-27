"use client";

import { useEffect, useState } from "react";
import { getHealth } from "@/lib/api";

export function HealthDot() {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    const check = () => getHealth().then((v) => { if (live) setOk(v); });
    check();
    const id = window.setInterval(check, 15000);
    return () => { live = false; window.clearInterval(id); };
  }, []);
  const label = ok === null ? "checking" : ok ? "live" : "offline";
  return (
    <div className={`health-dot health-dot--${ok === null ? "wait" : ok ? "ok" : "down"}`} role="status" aria-label={`Backend ${label}`}>
      <span /> {label}
    </div>
  );
}
