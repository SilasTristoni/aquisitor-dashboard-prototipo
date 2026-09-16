import { useRef } from "react";
import { Download } from "lucide-react";

export function ExportMenu({ disabled, items }: { disabled: boolean; items: Array<{ label: string; action: () => void }> }) {
  const menu = useRef<HTMLDetailsElement>(null);
  return <details ref={menu} className="export-menu" onKeyDown={(event) => {
    if (event.key === "Escape" && menu.current) { menu.current.open = false; menu.current.querySelector("summary")?.focus(); }
  }}><summary className="button primary" aria-disabled={disabled} onClick={(event) => { if (disabled) event.preventDefault(); }}><Download /> Exportar</summary>
    <div className="export-options" aria-label="Formatos de exportação">{items.map((item) => <button disabled={disabled} key={item.label} onClick={() => { if (menu.current) menu.current.open = false; item.action(); }}>{item.label}</button>)}</div>
  </details>;
}
