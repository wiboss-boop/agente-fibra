// Configuración del servicio `agente-fibra` en Railway (Infrastructure as Code).
//
// Sustituye a `railway.toml` (Config as Code), que Railway deja de leer el
// 2026-12-01. Railway NO lee este fichero al desplegar: solo se aplica a mano
// desde la raíz del repo, con Node >= 22 y `npm ci`:
//
//   railway config plan    # solo lee Railway y enseña el diff
//   railway config apply   # escribe los ajustes en el servicio
//
// - `partial`: este repo solo gestiona `agente-fibra`. El proyecto
//   reliable-delight también tiene `web` (secomcol-bot) y `function-bun`;
//   sin partial, un apply los daría por sobrantes y los borraría.
// - `variables: { managed: false }`: las variables (CREDENTIALS_YAML,
//   TELEGRAM_TOKEN, ACTIVE_SHEET_ID…) viven solo en Railway y no se tocan.
//   Con `managed: true`, las que no estén aquí se borrarían.
// - Sin `builder` a propósito: Railway construye con el Dockerfile porque lo
//   encuentra en la raíz. El `builder = "nixpacks"` del antiguo railway.toml
//   también se ignoraba por eso. Declarar `builder: "dockerfile"` no se guarda:
//   el apply del 10-nov-2026 lo dejó en null y el plan lo daba siempre como
//   pendiente. Si se borra el Dockerfile, el arranque pasa a Railpack.
// - `cronSchedule` va en UTC: 21:00 UTC son las 16:00 de Bogotá.
import { defineRailway, github, project, service } from "railway/iac";

export const partial = "agente-fibra";

export default defineRailway(() => {
  const agenteFibra = service("agente-fibra", {
    source: github("wiboss-boop/agente-fibra", { branch: "main", checkSuites: false }),
    build: { buildEnvironment: "V3" },
    start: "python start.py",
    replicas: { "us-west2": 1 },
    deploy: { cronSchedule: "0 21 * * *", restartPolicyType: "NEVER" },
  });

  return project("reliable-delight", {
    variables: { managed: false },
    resources: [agenteFibra],
  });
});
