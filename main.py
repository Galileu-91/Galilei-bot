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
from types import ModuleType

# --- BLINDAGEM CONTRA ERRO DE ÁUDIO ---
if 'audioop' not in sys.modules:
    mock_audioop = ModuleType('audioop')
    sys.modules['audioop'] = mock_audioop
    print("✅ Sistema de compatibilidade ativado (Sem erros de áudio)")

# --- CONFIGURAÇÃO WEB (KEEP ALIVE) ---
app = Flask('')
@app.route('/')
def home(): return "Bot Galilei está Online!"

def run():
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
        await interaction.response.send_message("Limpando sala...", ephemeral=True)
        await self.thread.delete()

    async def processar_clique(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Use sua própria sala!", ephemeral=True)

        self.respondido = True
        escolha_letra = interaction.data['custom_id'].upper()
        questoes = sessoes_usuarios[self.user_id]
        q_atual = questoes[self.index]

        mapeamento = self.message.content.split('\n')
        texto_escolhido = ""
        for linha in mapeamento:
            if linha.startswith(f"{escolha_letra}."):
                texto_escolhido = linha.split(". ", 1)[1].strip()

        if texto_escolhido.lower() == q_atual["texto_correto"].lower():
            self.acertos += 1
            feedback = f"✅ **Correto!**"
        else:
            feedback = f"❌ **Errado!** A resposta era: **{q_atual['texto_correto']}**"

        await interaction.response.edit_message(view=None)

        proximo = self.index + 1
        if proximo < len(questoes):
            q_prox = questoes[proximo]
            alts_texto = q_prox["alternativas"].copy()
            random.shuffle(alts_texto)
            
            novas_opcoes = [f"{l}. {t}" for l, t in zip(["A", "B", "C", "D"], alts_texto)]
            corpo_questao = f"**{q_prox['pergunta']}**\n\n" + "\n".join(novas_opcoes)

            nova_view = QuestaoView(self.user_id, proximo, self.acertos, self.thread)
            msg = await self.thread.send(
                content=f"{feedback}\n\n---\nQuestão {proximo + 1}:\n{corpo_questao}", 
                view=nova_view
            )
            nova_view.message = msg
        else:
            view_final = View()
            btn_repetir = Button(label="Repetir Simulado", style=discord.ButtonStyle.success, emoji="🔄")
            
            async def repetir_callback(it: discord.Interaction):
                await it.response.defer(ephemeral=True) 
                async for msg in self.thread.history(limit=100):
                    await msg.delete()

                random.shuffle(sessoes_usuarios[self.user_id])
                self.acertos = 0 
                self.index = 0   

                primeira_q = sessoes_usuarios[self.user_id][0]
                alts = primeira_q["alternativas"].copy()
                random.shuffle(alts)
                
                nova_view = QuestaoView(self.user_id, 0, 0, self.thread)
                opcoes = [f"{l}. {t}" for l, t in zip(["A", "B", "C", "D"], alts)]
                
                msg = await self.thread.send(
                    content=f"🎲 **Simulado Reiniciado!**\n\nQuestão 1:\n**{primeira_q['pergunta']}**\n\n" + "\n".join(opcoes), 
                    view=nova_view
                )
                nova_view.message = msg
            btn_repetir.callback = repetir_callback
            
            # ✅ O btn_sair foi removido daqui para o Galilei não "dormir" por engano
            view_final.add_item(btn_repetir)

            await self.thread.send(
                content=f"{feedback}\n\n🏆 **Simulado Concluído!**\nAcertos: **{self.acertos}/{len(questoes)}**", 
                view=view_final
            )

            # ✅ CORREÇÃO DO ERRO DO VS CODE (self.acertos)
            await self.thread.send(
                content=f"{feedback}\n\n🏆 **Simulado Concluído!**\nAcertos: **{self.acertos}/{len(questoes)}**", 
                view=view_final
            )

# --- MENU PRINCIPAL (ESTILO ALFREDO) ---

class MenuSimulado(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Probabilidade e Estatística", style=discord.ButtonStyle.secondary, row=1)
    async def btn1(self, it, btn): await self.preparar_sala(it, "Probabilidade e Estatística.txt")

    @discord.ui.button(label="Fundamentos de Sistemas de Informação", style=discord.ButtonStyle.secondary, row=1)
    async def btn2(self, it, btn): await self.preparar_sala(it, "Fundamentos de Sistemas de Informação.txt")

    @discord.ui.button(label="Fundamentos de Gestão Empresarial", style=discord.ButtonStyle.secondary, row=2)
    async def btn3(self, it, btn): await self.preparar_sala(it, "Fundamentos de Gestão Empresarial.txt")

    async def preparar_sala(self, interaction, nome_arquivo):
        # 1. Cria a thread primeiro
        thread = await interaction.channel.create_thread(
            name=f"Estudo-{interaction.user.name}",
            type=discord.ChannelType.public_thread,
            auto_archive_duration=1440
        )
        
        # 2. Responde UMA ÚNICA VEZ (Isso evita a duplicação e o erro de interação)
        await interaction.response.send_message(f"✅ Sala criada, clique aqui 👉 {thread.mention}", ephemeral=True)
        
        # 3. Chama a lógica de carregar as questões
        await self.iniciar_logica(interaction, nome_arquivo, thread)

    async def iniciar_logica(self, interaction, nome_arquivo, thread):
        caminho = os.path.join("Simulados", nome_arquivo)
        if not os.path.exists(caminho):
            return await thread.send(f"❌ Arquivo `{nome_arquivo}` não encontrado no servidor.")

        # Aviso visual na thread
        msg_loading = await thread.send("📘 **Iniciando simulado...**")
      
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                conteudo = f.read()
                # Divide o arquivo pelos separadores ---
                blocos = [b for b in conteudo.split("---") if b.strip()]

            questoes_lista = []
            
            for bloco in blocos:
                linhas = [l.strip() for l in bloco.strip().split('\n') if l.strip()]
                
                pergunta_completa = []
                alts_dict = {}
                texto_correto = ""
                fase_pergunta = True 

                for linha in linhas:
                    # ✅ Identifica as alternativas A, B, C ou D
                    if re.match(r"^[A-D]:", linha.upper()):
                        fase_pergunta = False
                        letra = linha[0].upper()
                        texto = linha[2:].strip()
                        alts_dict[letra] = texto
                    # ✅ Identifica o início da questão
                    elif linha.upper().startswith("QUESTAO:"):
                        pergunta_completa.append(linha.replace("QUESTAO:", "").strip())
                    # ✅ Identifica o Gabarito
                    elif linha.upper().startswith("GABARITO:"):
                        letra_gab = linha.replace("GABARITO:", "").strip().upper()
                        if letra_gab in alts_dict:
                            texto_correto = alts_dict[letra_gab]
                    # ✅ Se estiver na fase da pergunta, acumula (inclui I, II, III...)
                    elif fase_pergunta:
                        pergunta_completa.append(linha)

                # Só adiciona se a questão estiver completa
                if pergunta_completa and texto_correto:
                    questoes_lista.append({
                        "pergunta": "\n".join(pergunta_completa),
                        "alternativas": list(alts_dict.values()),
                        "texto_correto": texto_correto
                    })

            if questoes_lista:
                # Armazena todas as questões na sessão do usuário
                random.shuffle(questoes_lista)
                sessoes_usuarios[interaction.user.id] = questoes_lista
                
                q = questoes_lista[0]
                
                # Embaralha as alternativas para exibição
                alts_exibicao = q["alternativas"].copy()
                random.shuffle(alts_exibicao)
                opcoes_texto = [f"{l}. {t}" for l, t in zip(["A", "B", "C", "D"], alts_exibicao)]
                
                view = QuestaoView(interaction.user.id, 0, 0, thread)
                
                # Deleta o "carregando" e manda a primeira questão com tudo (I, II, III...)
                await msg_loading.delete()
                msg = await thread.send(content=f"Questão 1:\n**{q['pergunta']}**\n\n" + "\n".join(opcoes_texto), view=view)
                view.message = msg
            else:
                await thread.send("⚠️ Erro: Não encontrei questões válidas no formato QUESTAO/GABARITO.")

        except Exception as e:
            print(f"Erro técnico: {e}")
            await thread.send(f"❌ Ocorreu um erro ao processar o simulado.")

# --- COMANDOS (SEU CABEÇALHO COMPLETO) ---
@bot.command()
async def menu(ctx):
    embed = discord.Embed(
        title="📚 Central de Simulados (1/1)",
        description=(
            "Aqui estão as provas disponíveis neste servidor.\n"
            "Você pode iniciar um simulado clicando no botão correspondente abaixo.\n\n"
            "**Probabilidade e Estatística**\n"
            "📌 Vinculado por: @Galileu Meirelles\n\n"
            "**Fundamentos de Sistemas de Informação**\n"
            "📌 Vinculado por: @Galileu Meirelles\n\n"
            "**Fundamentos de Gestão Empresarial**\n"
            "📌 Vinculado por: @Galileu Meirelles\n\n"
            "🔹 *Clique em um dos botões abaixo para abrir sua sala privada!*"
        ),
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=MenuSimulado())

@bot.command(name="limpar")
@commands.has_permissions(manage_messages=True)
async def limpar(ctx, quantidade: int = 100):
    try:
        # 1. Tenta apagar a mensagem do comando !limpar
        await ctx.message.delete()
        
        # 2. Faz a limpeza (o purge funciona em Threads se o bot tiver permissão)
        deleted = await ctx.channel.purge(limit=min(quantidade, 100))
        
        # 3. Feedback rápido e autodeletável
        await ctx.send(f"🧹 Faxina concluída! {len(deleted)} mensagens removidas por ordem do Mano Gali.", delete_after=5)
        print(f"✅ Limpeza executada por {ctx.author} em {ctx.channel.name}")

    except discord.errors.Forbidden:
        await ctx.send("❌ Erro: O Galilei não tem permissão de 'Gerenciar Mensagens' ou 'Gerenciar Threads' neste canal.")
    except Exception as e:
        print(f"❌ Erro no !limpar: {e}")

@bot.event
async def on_ready():
    print(f"✅ Galilei#0213 Online | Visual Alfredo | Sistema de Threads")

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)