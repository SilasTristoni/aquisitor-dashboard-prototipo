import { PortalConfiguration } from "../components/PortalConfiguration";
import { PageHeader, Panel } from "../components/ui";

export default function PortalConfigurationPage() {
  return <>
    <PageHeader eyebrow="CONFIGURAÇÃO" title="Portal externo" description="Configure a conexão segura com o portal de resultados no Render, mesmo antes do primeiro ensaio." />
    <Panel>
      <PortalConfiguration expanded />
      <p className="hint">Após configurar o portal, abra uma sessão finalizada para selecionar os resultados e publicar o link. Relatórios locais continuam disponíveis.</p>
    </Panel>
  </>;
}
