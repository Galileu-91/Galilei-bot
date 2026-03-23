import discord
from discord.ext import commands
from discord.ui import Button, View
import re
import os
import asyncio
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- CONFIGURAÇÃO WEB (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Galilei está Online!"

def run():
    # O Render define a porta automaticamente; se não houver, usa 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True # Garante que a thread feche com o bot
    t.start()

# --- CONFIGURAÇÕES DO BOT ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix='!', intents=intents)

sessoes_usuarios = {}

# --- INTERFACE DAS QUESTÕES ---
class QuestaoView(View):
    def __init__(self, user_id, index, acertos, thread):
        super().__init__(timeout=360) 
        self.user_id = user_id
        self.index = index
        self.acertos = acertos
        self.thread = thread
        self.respondido = False
        self.message = None

        for letra in ["A", "B", "C", "D"]:
            btn = Button(label=letra, style=discord.ButtonStyle.blurple, custom_id=letra)
            btn.callback = self.processar_clique
            self.add_item(btn)

        btn_reset = Button(label="Sair/Reset", style=discord.ButtonStyle.secondary, emoji="🔄")
        btn_reset.callback = self.resetar_simulado
        self.add_item(btn_reset)

        asyncio.create_task(self.contagem_regressiva())

    async def contagem_regressiva(self):
        await asyncio.sleep(240) 
        if not self.respondido and self.message:
            try:
                for item in self.children:
                    if isinstance(item, Button) and item.label != "Sair/Reset":
                        item.disabled = True
                await self.message.edit(content=f"{self.message.content}\n\n⏰ **Tempo esgotado (240s)!**", view=self)
            except: pass

    async def resetar_simulado(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Não é sua sala!", ephemeral=True)
        await interaction.response.send_message("Limpando sala...", ephemeral=True)
        await self.thread.delete()

    async def processar_clique(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Use sua própria sala!", ephemeral=True)

        self.respondido = True
        escolha = interaction.data['custom_id'].upper()
        questoes = sessoes_usuarios[self.user_id]

        try:
            correta = questoes[self.index]["correta"]
        except (KeyError, IndexError):
            correta = "A"

        novos_acertos = self.acertos
        feedback = "✅ **Correto!**" if escolha == correta else f"❌ **Errado!** A resposta era **{correta}**."
        if escolha == correta: novos_acertos += 1

        await interaction.response.edit_message(view=None)

        proximo = self.index + 1
        if proximo < len(questoes):
            q = questoes[proximo]
            nova_view = QuestaoView(self.user_id, proximo, novos_acertos, self.thread)
            msg = await self.thread.send(
                content=f"{feedback}\n\n---\n**Questão {proximo + 1}:**\n{q['pergunta']}", 
                view=nova_view
            )
            nova_view.message = msg
        else:
            view_final = View()
            btn_sair = Button(label="Finalizar e Apagar Sala", style=discord.ButtonStyle.danger, emoji="扫")
            btn_sair.callback = lambda it: asyncio.create_task(self.thread.delete())
            view_final.add_item(btn_sair)

            await self.thread.send(
                content=f"{feedback}\n\n🏆 **Simulado Concluído!**\nAcertos: **{novos_acertos}/{len(questoes)}**", 
                view=view_final
            )

# --- MENU PRINCIPAL (VISUAL DO ALFREDO) ---
class MenuSimulado(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Teste 1", style=discord.ButtonStyle.secondary, row=1)
    async def btn_plan(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.preparar_sala(interaction, "Teste de prova 1.txt")

    @discord.ui.button(label="Teste 2", style=discord.ButtonStyle.secondary, row=1)
    async def btn_seg(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.preparar_sala(interaction, "Gestao Seguranca.txt")

    @discord.ui.button(label="Teste 3", style=discord.ButtonStyle.secondary, row=2)
    async def btn_sad(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.preparar_sala(interaction, "Sistemas Apoio Decisao.txt")

    async def preparar_sala(self, interaction, nome_arquivo):
        thread = await interaction.channel.create_thread(
            name=f"Estudo-{interaction.user.name}",
            type=discord.ChannelType.public_thread 
        )
        await interaction.response.send_message(f"✅ Sala criada: {thread.mention}", ephemeral=True)
        await self.iniciar_logica(interaction, nome_arquivo, thread)

    async def iniciar_logica(self, interaction, nome_arquivo, thread):
        caminho = os.path.join("Simulados", nome_arquivo)
        if not os.path.exists(caminho):
            return await thread.send(f"❌ Arquivo `{nome_arquivo}` não encontrado na pasta /Simulados.")

        with open(caminho, 'r', encoding='utf-8') as f:
            conteudo = f.read()

        blocos = re.split(r'\n(?=\d+\.)', conteudo)
        questoes_lista = []
        for bloco in blocos:
            if not bloco.strip(): continue
            res = re.search(r'(?:A )?resposta correta é:\s*([a-d])', bloco, re.IGNORECASE)
            gabarito = res.group(1).upper() if res else "A"
            enunciado = re.split(r'A resposta correta é:|Resposta correta é:', bloco, flags=re.IGNORECASE)[0].strip()
            questoes_lista.append({"pergunta": enunciado[:1900], "correta": gabarito})

        sessoes_usuarios[interaction.user.id] = questoes_lista
        view = QuestaoView(interaction.user.id, 0, 0, thread)
        msg = await thread.send(f"📖 **Iniciando: {nome_arquivo}**\n\n**Questão 1:**\n{questoes_lista[0]['pergunta']}", view=view)
        view.message = msg

# --- COMANDOS ---
@bot.command()
async def menu(ctx):
    embed = discord.Embed(
        title="📚 Central de Simulados (1/1)",
        description="Selecione uma matéria abaixo para iniciar seu simulado em uma sala privada.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=MenuSimulado())

@bot.event
async def on_ready():
    print(f"✅ Galilei#0213 Online | Visual Alfredo | Sistema de Threads")

# --- INICIALIZAÇÃO ---
if __name__ == "__main__":
    if TOKEN:
        keep_alive()
        import time
        print("⏳ Aguardando 10 segundos para estabilizar conexão...")
        time.sleep(10)
        bot.run(TOKEN)
    else:
        print("❌ ERRO: DISCORD_TOKEN não encontrado!")