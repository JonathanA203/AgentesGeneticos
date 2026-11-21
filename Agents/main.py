import time
import asyncio

from config import XMPP_SERVER, PASSWORD
from agents.parent_agent import ParentAgent


# ==========================================
# PUNTO DE ENTRADA PRINCIPAL
# ==========================================
async def main():
    print("Iniciando Sistema Multi-Agente v1...")

    padre_jid = f"padre_orquestador_{int(time.time())}@{XMPP_SERVER}"
    padre = ParentAgent(padre_jid, PASSWORD)

    await padre.start(auto_register=True)

    # Mantener el script vivo mientras el padre siga activo
    while padre.is_alive():
        try:
            await asyncio.sleep(1)
        except KeyboardInterrupt:
            break

    print("Apagando motor SPADE...")
    await padre.stop()


if __name__ == "__main__":
    # SPADE requiere que se ejecute el loop asíncrono
    asyncio.run(main())
