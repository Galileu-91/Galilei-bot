import time
import random
import discord
from discord.ext import commands
from discord.ui import Button, View
import re
import os
import asyncio
import sys
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

import sys
from types import ModuleType

# --- BLINDAGEM CONTRA ERRO DE ÁUDIO ---
# Isso engana o VS Code e o Render para não pedirem a biblioteca audioop
if 'audioop' not in sys.modules:
    mock_audioop = ModuleType('audioop')
    sys.modules['audioop'] = mock_audioop
    print("✅ Sistema de compatibilidade ativado (Sem erros de áudio)")

# --- CONFIGURAÇÃO WEB (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Galilei está Online!"

def run():
    # Render usa porta dinâmica; se não achar, usa 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# --- CONFIGURAÇÕES DO BOT ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix='!', intents=intents)

sessoes_usuarios = {}

# --- INTERFACE DAS QUESTÕES (LOGICA COMPLETA) ---
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

        bot.loop.create_task(self.contagem_regressiva())

    async def contagem_regressiva(self):
        await asyncio.sleep(240) 
        if not self.respondido and self.message:
            try:
                for item in self.children:
                    if isinstance(item, Button) and item.label != "Sair/Reset":
                        item.disabled = True
                await self.message.edit(content=f"{self.message.content}\n\n⏰ **Tempo esgotado (240s)!**", view=self)
            except: pass

    async def on_timeout(self):
        try: await self.thread.delete()
        except: pass

    async def resetar_simulado(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Não é sua sala!", ephemeral=True)
        # ✅ Responde ao Discord antes de deletar a thread
        await interaction.response.send_message("Limpando sala...", ephemeral=True)
        await self.thread.delete()

    async def processar_clique(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Use sua própria sala!", ephemeral=True)

        self.respondido = True
        escolha_letra = interaction.data['custom_id'].upper()
        questoes = sessoes_usuarios[self.user_id]
        q_atual = questoes[self.index]

        # ✅ LÓGICA DE VALIDAÇÃO: Compara o texto da opção clicada com o texto correto
        # Mapeia qual texto está em qual letra agora
        mapeamento = self.message.content.split('\n')
        texto_escolhido = ""
        for linha in mapeamento:
            if linha.startswith(f"{escolha_letra}."):
                texto_escolhido = linha.replace(f"{escolha_letra}. ", "").strip()

        if texto_escolhido.lower() == q_atual["texto_correto"].lower():
            self.acertos += 1
            feedback = f"✅ **Correto!**"
        else:
            feedback = f"❌ **Errado!** A resposta era: **{q_atual['texto_correto']}**"

        await interaction.response.edit_message(view=None)

        proximo = self.index + 1
        if proximo < len(questoes):
            # ✅ EMBARALHA AS LETRAS PARA A PRÓXIMA QUESTÃO
            q_prox = questoes[proximo]
            alts_texto = [re.sub(r'^[a-d][\s\.)]+', '', a).strip() for a in q_prox["alternativas"]]
            random.shuffle(alts_texto)
            
            # Monta o novo texto com a., b., c., d.
            novas_opcoes = [f"{l}. {t}" for l, t in zip(["a", "b", "c", "d"], alts_texto)]
            corpo_questao = f"{q_prox['pergunta']}\n\n" + "\n".join(novas_opcoes)

            nova_view = QuestaoView(self.user_id, proximo, self.acertos, self.thread)
            msg = await self.thread.send(
                content=f"{feedback}\n\n---\nQuestão {proximo + 1}:\n{corpo_questao}", 
                view=nova_view
            )
            nova_view.message = msg

        else:
            # --- BLOCO ALTERADO PARA REPETIR ---
            view_final = View()
            
            # Botão para Repetir (Limpa e Reinicia)
            btn_repetir = Button(label="Repetir Simulado", style=discord.ButtonStyle.success, emoji="🔄")
            
            async def repetir_callback(it: discord.Interaction):
                # ✅ Avisa o Discord para esperar o processo de limpeza (purge)
                await it.response.defer(ephemeral=True) 
                
                async for msg in self.thread.history(limit=100):
                    await msg.delete()

                random.shuffle(sessoes_usuarios[self.user_id])

                self.acertos = 0 
                self.index = 0   

                primeira_q = sessoes_usuarios[self.user_id][0]
                nova_view = QuestaoView(self.user_id, 0, 0, self.thread)
                
                # ✅ Texto ajustado para letra menor aqui também
                msg = await self.thread.send(
                    content=f"🎲 **Simulado Embaralhado!**\n\nQuestão 1:\n{primeira_q['pergunta']}", 
                    view=nova_view
                )
                nova_view.message = msg

            btn_repetir.callback = repetir_callback
            
            # Mantive o de apagar sala como segunda opção caso você queira fechar
            btn_sair = Button(label="Apagar Sala", style=discord.ButtonStyle.danger, emoji="🧹")
            btn_sair.callback = lambda it: asyncio.create_task(self.thread.delete())
            
            view_final.add_item(btn_repetir)
            view_final.add_item(btn_sair)

            await self.thread.send(
                content=f"{feedback}\n\n🏆 **Simulado Concluído!**\nAcertos: **{self.acertos}/{len(questoes)}**", 
                view=view_final
            )

# --- MENU PRINCIPAL (VISUAL DO ALFREDO) ---
class MenuSimulado(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Probabilidade e Estatística", style=discord.ButtonStyle.secondary, row=1)
    async def btn_plan(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.preparar_sala(interaction, "Probabilidade e Estatística.txt")

    @discord.ui.button(label="Fundamentos de Sistemas de Informação", style=discord.ButtonStyle.secondary, row=1)
    async def btn_seg(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.preparar_sala(interaction, "Fundamentos de Sistemas de Informação.txt")

    @discord.ui.button(label="Fundamentos de Gestão Empresarial", style=discord.ButtonStyle.secondary, row=2)
    async def btn_sad(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.preparar_sala(interaction, "Fundamentos de Gestão Empresarial.txt")

    async def preparar_sala(self, interaction, nome_arquivo):
    # ✅ cria a thread DESARQUIVADA
        thread = await interaction.channel.create_thread(
        name=f"Estudo-{interaction.user.name}",
        type=discord.ChannelType.public_thread,
        auto_archive_duration=1440
    )

    # ✅ libera a interaction (obrigatório)
        await interaction.response.defer(ephemeral=True)

    # ✅ AVISO IMEDIATO (debug + UX)
        await thread.send("📘 Simulado iniciado... carregando questões")

    # ✅ chama a lógica DIRETAMENTE (sem create_task)
        await self.iniciar_logica(interaction, nome_arquivo, thread)

    # ✅ feedback ao usuário
        await interaction.followup.send(
        f"✅ Sala criada: {thread.mention}",
        ephemeral=True
    )
    
        await interaction.response.send_message(f"✅ Sala criada, clique aqui👉🏼: {thread.mention}", ephemeral=True)
        await self.iniciar_logica(interaction, nome_arquivo, thread)

async def iniciar_logica(self, interaction, nome_arquivo, thread):
        caminho = os.path.join("Simulados", nome_arquivo)
        if not os.path.exists(caminho):
            return await thread.send(f"❌ Arquivo `{nome_arquivo}` não encontrado.")

        with open(caminho, "r", encoding="utf-8") as f:
            conteudo = f.read()

        # 🔹 Separa as questões pelo fechamento do bloco #]
        blocos = [b.strip() for b in conteudo.split("#]") if b.strip()]
        questoes_lista = []

        for bloco in blocos:
            # 1. Extrai o enunciado (Tudo entre [# e o fim do texto antes das chaves)
            match_pergunta = re.search(r'\[#\s*(.*?)(?=\{[a-d]\})', bloco, re.DOTALL | re.IGNORECASE)
            if not match_pergunta:
                continue
            
            pergunta_texto = match_pergunta.group(1).strip()

            # 2. Extrai Alternativas {a} texto
            alternativas = {}
            for alt in re.findall(r'\{([a-d])\}\s*([^\n{<]+)', bloco, re.IGNORECASE):
                letra = alt[0].lower()
                texto = alt[1].strip()
                alternativas[letra] = texto

            # 3. Extrai Resposta correta <Resposta correta: d> ou <d>
            match_resp = re.search(r'<\s*Resposta correta:\s*([a-d])\s*>', bloco, re.IGNORECASE)
            if not match_resp:
                # Tenta um padrão mais simples caso o anterior falhe
                match_resp = re.search(r'<([a-d])>', bloco, re.IGNORECASE)

            if match_resp and alternativas:
                letra_correta = match_resp.group(1).lower()
                if letra_correta in alternativas:
                    questoes_lista.append({
                        "pergunta": pergunta_texto,
                        "alternativas": list(alternativas.values()),
                        "texto_correto": alternativas[letra_correta]
                    })

        if not questoes_lista:
            return await thread.send("⚠️ Formato inválido! Certifique-se de usar `[# texto #]`, `{a} opção` e `<Resposta correta: a>`.")

        # 🔹 Embaralha e Inicia (Lógica que já estava funcionando)
        random.shuffle(questoes_lista)
        sessoes_usuarios[interaction.user.id] = questoes_lista
        q = questoes_lista[0]
        alts = q["alternativas"].copy()
        random.shuffle(alts)

        letras = ["a", "b", "c", "d"]
        opcoes = [f"{letras[i]}. {alts[i]}" for i in range(len(alts))]
        corpo = f"**{q['pergunta']}**\n\n" + "\n".join(opcoes)

        view = QuestaoView(interaction.user.id, 0, 0, thread)
        msg = await thread.send(content=f"📘 **Simulado iniciado**\n\nQuestão 1:\n{corpo}", view=view)
        view.message = msg

# --- COMANDOS ---
@bot.command()
async def menu(ctx):
    embed = discord.Embed(
        title="📚 Central de Simulados (1/1)",
        description=
            "Aqui estão as provas disponíveis neste servidor.\n"
            "Você pode iniciar um simulado clicando no botão correspondente abaixo.\n\n"
            "**Probabilidade e Estatística**\n"
            "📌 Vinculado por: @Galileu Meirelles\n\n"
            "**Fundamentos de Sistemas de Informação**\n"
            "📌 Vinculado por: @Galileu Meirelles\n\n"
            "**Fundamentos de Gestão Empresarial**\n"
            "📌 Vinculado por: @Galileu Meirelles\n\n"
            "🔹 *Clique em um dos botões abaixo para abrir sua sala privada!*",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=MenuSimulado())

@bot.event
async def on_ready():
    print(f"✅ Galilei#0213 Online | Visual Alfredo | Sistema de Threads")

@bot.command(name="limpar")
@commands.has_permissions(manage_messages=True)
async def limpar(ctx, quantidade: int = 100):

    try:
        # ✅ Apaga o comando !limpar enviado pelo usuário primeiro
        await ctx.message.delete()
        
        limite = min(quantidade, 100)
        deleted = await ctx.channel.purge(limit=limite)
        
        await ctx.send(f"🧹 {len(deleted)} mensagens limpas por ordem do Mano Gali!", delete_after=3)
        print(f"✅ Faxina concluída no canal {ctx.channel.name}")
    except Exception as e:
        print(f"❌ Erro na limpeza: {e}")

import threading

# --- INICIALIZAÇÃO SEGURA ---
if __name__ == "__main__":
    if TOKEN:
        print("🚀 Iniciando servidor de manutenção...")
        # Cria a thread para o Flask não travar o bot
        t = threading.Thread(target=keep_alive)
        t.daemon = True
        t.start()

        print("🤖 Tentando conectar o Galilei ao Discord...")
        try:
            bot.run(TOKEN) # O comando que pode dar erro fica dentro do try
        except discord.errors.HTTPException as e:
            if e.status == 429:
                print("Rate limit detectado. Aguardando 30s...")
                time.sleep(30) # Pausa técnica antes de qualquer tentativa automática
            else:
                print(f"Erro de conexão: {e}")
    else:
        print("❌ ERRO: DISCORD_TOKEN não encontrado nas variáveis de ambiente.")