import { useEffect, useState } from "react";
import { api } from "../api";

export type Identity = { identity_id: string | null; company_name: string; laboratory: string; logo: string | null };
export function CompanyMark({ identity }: { identity?: Identity | null }) {
  if (!identity?.company_name) return null;
  return <div className="company-mark">{identity.logo?.startsWith("data:image/png;base64,") && <img src={identity.logo} alt={`Logotipo de ${identity.company_name}`} />}<div><strong>{identity.company_name}</strong>{identity.laboratory && <small>{identity.laboratory}</small>}</div></div>;
}

export function CurrentCompanyMark() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  useEffect(() => {
    const refresh = () => { void api<Identity>("/company-identity").then(setIdentity).catch(() => setIdentity(null)); };
    refresh();
    window.addEventListener("company-identity-changed", refresh);
    return () => window.removeEventListener("company-identity-changed", refresh);
  }, []);
  return <CompanyMark identity={identity} />;
}
