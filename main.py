from itertools import islice
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
        # 1. Trava de ID (Segurança de usuário)
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Use sua própria sala!", ephemeral=True)

        # ✅ 2. TRAVA DE DUPLICIDADE: Se já respondeu, ignora qualquer outro clique
        if self.respondido:
            return
        
        self.respondido = True # Tranca a porta aqui
        
        escolha_letra = interaction.data['custom_id'].upper()
        questoes = sessoes_usuarios[self.user_id]
        q_atual = questoes[self.index]

       # Validação direta e blindada via memória do objeto
        texto_correto = q_atual["texto_correto"].lower()
        
        # Pega a alternativa diretamente pelo índice de memória da View (A=0, B=1, C=2, D=3)
        index_letra = ord(escolha_letra) - 65
        texto_escolhido = self.alternativas_atuais[index_letra]

        if texto_escolhido.lower() == q_atual["texto_correto"].lower():
            self.acertos += 1
            feedback = f"✅ **Correto!**"
        else:
            feedback = f"❌ **Errado!** A resposta era: **{q_atual['texto_correto']}**"

        # Remove os botões da questão atual após o clique
        await interaction.response.edit_message(view=None)

        proximo = self.index + 1
        if proximo < len(questoes):
            # --- SEGUE PARA A PRÓXIMA QUESTÃO ---
            q_prox = questoes[proximo]
            alts_texto = q_prox["alternativas"].copy()
            random.shuffle(alts_texto)
            
            # Envia o feedback da resposta anterior separado antes da nova questão
            await self.thread.send(content=feedback)

            # --- HIGIENIZAÇÃO DA PRÓXIMA PERGUNTA ---
            pergunta_limpa = q_prox['pergunta'].replace("QUESTÃO:", "").replace("QUESTAO:", "").strip()

            # Monta o bloco de alternativas direto para a descrição
            bloco_opcoes = ""
            for l, t in zip(["A", "B", "C", "D"], alts_texto):
                texto_alt_limpo = re.sub(r'^[A-D]:\s*', '', t)
                bloco_opcoes += f"**{l})** {texto_alt_limpo}\n"

            embed_prox = discord.Embed(
                title=f"Questão {proximo + 1}",
                description=f"{pergunta_limpa}\n\n{bloco_opcoes}",
                color=discord.Color.blue()
            )
            
            if q_prox["imagem"]:
                embed_prox.set_image(url=q_prox["imagem"])

            nova_view = QuestaoView(self.user_id, proximo, self.acertos, self.thread)
            nova_view.alternativas_atuais = alts_texto # Passa a ordem de memória adiante
            
            msg = await self.thread.send(embed=embed_prox, view=nova_view)
            nova_view.message = msg
        else:
            # --- FINALIZA O SIMULADO ---
            self.stop()
            await self.thread.send(content=feedback)
            
            view_final = View()
            btn_repetir = Button(label="Repetir Simulado", style=discord.ButtonStyle.success, emoji="🔄")
            
            async def repetir_callback(it: discord.Interaction):
                await it.response.defer(ephemeral=True) 
                async for msg in self.thread.history(limit=100):
                    await msg.delete()
                
                random.shuffle(sessoes_usuarios[self.user_id])
                # IMPORTANTE: Passa '0' no 3º argumento para zerar a contagem de acertos ao reiniciar
                nova_v = QuestaoView(self.user_id, 0, 0, self.thread)
                q_ini = sessoes_usuarios[self.user_id][0]
                alts = q_ini["alternativas"].copy()
                random.shuffle(alts)
                
                pergunta_ini_limpa = q_ini['pergunta'].replace("QUESTÃO:", "").replace("QUESTAO:", "").strip()
                bloco_ini_opcoes = ""
                for l, t in zip(["A", "B", "C", "D"], alts):
                    texto_alt_limpo = re.sub(r'^[A-D][:\.]\s*', '', t)
                    bloco_ini_opcoes += f"**{l})** {texto_alt_limpo}\n"

                embed_reiniciar = discord.Embed(
                    title="Questão 1",
                    description=f"🎲 **Simulado Reiniciado!**\n\n{pergunta_ini_limpa}\n\n{bloco_ini_opcoes}",
                    color=discord.Color.blue()
                )
                
                if q_ini["imagem"]:
                    embed_reiniciar.set_image(url=q_ini["imagem"])
                    
                nova_v.alternativas_atuais = alts
                m = await self.thread.send(embed=embed_reiniciar, view=nova_v)
                nova_v.message = m

            btn_repetir.callback = repetir_callback
            view_final.add_item(btn_repetir)

            # CÁLCULO DINÂMICO E PRECISO DA NOTA
            total_questoes = len(questoes)
            acertos_finais = min(self.acertos, total_questoes)
            nota = (acertos_finais / total_questoes) * 10.0 if total_questoes > 0 else 0.0

            # MENSAGEM FINAL LIMPA (Sem a resposta da última questão colada)
            await self.thread.send(
                content=(
                    f"🏆 **Simulado Concluído!**\n"
                    f"Acertos: **{acertos_finais}/{total_questoes}** | Nota: **{nota:.1f}**"
                ),
                view=view_final
            )

# --- MENU PRINCIPAL (ESTILO ALFREDO) ---

class MenuSimulado(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Algoritmos Para Programação", emoji="💻", style=discord.ButtonStyle.primary, row=0)
    async def btn1(self, it, btn): await self.preparar_sala(it, "Algoritmos Para Programação.txt")

    @discord.ui.button(label="Arquitetura de Computadores", emoji="🖥️", style=discord.ButtonStyle.primary, row=0)
    async def btn2(self, it, btn): await self.preparar_sala(it, "Arquitetura de Computadores.txt")

    @discord.ui.button(label="Engenharia de Software", emoji="⚙️", style=discord.ButtonStyle.primary, row=0)
    async def btn3(self, it, btn): await self.preparar_sala(it, "Engenharia de Software.txt")

    @discord.ui.button(label="Inteligência Artificial", emoji="🤖", style=discord.ButtonStyle.primary, row=0)
    async def btn4(self, it, btn): await self.preparar_sala(it, "Inteligência Artificial.txt")

    @discord.ui.button(label="Introdução à Ciência de Dados", emoji="📊", style=discord.ButtonStyle.primary, row=1)
    async def btn5(self, it, btn): await self.preparar_sala(it, "Introdução à Ciência de Dados.txt")

    @discord.ui.button(label="Rede de Computadores", emoji="🌐", style=discord.ButtonStyle.primary, row=1)
    async def btn6(self, it, btn): await self.preparar_sala(it, "Rede de Computadores.txt")

    @discord.ui.button(label="Sistemas Operacionais", emoji="🐧", style=discord.ButtonStyle.primary, row=1)
    async def btn7(self, it, btn): await self.preparar_sala(it, "Sistemas Operacionais.txt")

    @discord.ui.button(label="Teoria Geral dos Sistemas", emoji="🧠", style=discord.ButtonStyle.primary, row=1)
    async def btn8(self, it, btn): await self.preparar_sala(it, "Teoria Geral dos Sistemas.txt")


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
                    # ✅ Imagem
                    elif linha.upper().startswith("IMAGEM:"):
                        imagem_url = linha.replace("IMAGEM:", "").strip()

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
                        "texto_correto": texto_correto,
                        "imagem": imagem_url if 'imagem_url' in locals() else None
                    })
                    #Limpa imagem_url para não vazar para a próxima questão
                    if 'imagem_url' in locals():
                        del imagem_url

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
                
                # --- HIGIENIZAÇÃO DA PRIMEIRA PERGUNTA ---
                pergunta_ini_limpa = q['pergunta'].replace("QUESTÃO:", "").replace("QUESTAO:", "").strip()
                
                # Gera o bloco de alternativas textual limpo dentro da própria descrição
                bloco_opcoes = ""
                for l, t in zip(["A", "B", "C", "D"], alts_exibicao):
                    texto_alt_limpo = re.sub(r'^[A-D]:\s*', '', t)
                    bloco_opcoes += f"**{l})** {texto_alt_limpo}\n"
                
                view = QuestaoView(interaction.user.id, 0, 0, thread)
                view.alternativas_atuais = alts_exibicao # Salva a ordem na memória da View
                
                await msg_loading.delete()
                
                embed = discord.Embed(
                    title="Questão 1", 
                    description=f"{pergunta_ini_limpa}\n\n{bloco_opcoes}",
                    color=discord.Color.blue()
                )


                if q["imagem"]:
                    embed.set_image(url=q["imagem"])

                
                msg = await thread.send(embed=embed, view=view)
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
        title="🎓Central de Simulados & Estudos🎓",
        description=(
            "Bem-vindo(a) à sua plataforma de treino!\n"
            "Selecione uma disciplina abaixo para gerar uma **sala de estudos privada**.\n\n"
            "📌 **DISCIPLINAS DISPONÍVEIS:**\n"
            "💻 `Algoritmos Para Programação`\n"
            "🖥️ `Arquitetura de Computadores`\n"
            "⚙️ `Engenharia de Software`\n"
            "🤖 `Inteligência Artificial`\n"
            "📊 `Introdução à Ciência de Dados`\n"
            "🌐 `Rede de Computadores`\n"
            "🐧 `Sistemas Operacionais`\n"
            "🧠 `Teoria Geral dos Sistemas`\n\n"
            "**Organizado por:** @Galileu Meirelles\n"
            "-----------------------------------------\n"
            "👇 **Clique em um dos botões abaixo para iniciar:**"
        ),
        color=discord.Color.blue()
    )
    # Adiciona um rodapé estilizado no Embed
    embed.set_footer(text="Bot Galilei • Bons estudos!", icon_url=bot.user.display_avatar.url)
    await ctx.send(embed=embed, view=MenuSimulado())

@bot.command(name="limpar")
@commands.has_permissions(manage_messages=True)
async def limpar(ctx, quantidade: int = 100):
    try:
        # Apaga a mensagem que chamou o comando
        try:
            await ctx.message.delete()
        except Exception:
            pass
        
        # Limpa o canal ou thread
        deleted = await ctx.channel.purge(limit=min(quantidade, 100))
        
        # Envia aviso temporário e deleta após 3 segundos
        msg_feedback = await ctx.send(f"🧹 Faxina concluída! {len(deleted)} mensagens removidas por ordem do Mano Gali.")
        await asyncio.sleep(3)
        await msg_feedback.delete()

        print(f"✅ Limpeza executada por {ctx.author} em {ctx.channel.name}")

    except discord.errors.Forbidden:
        await ctx.send("❌ Erro: O Galilei não tem permissão de 'Gerenciar Mensagens' ou 'Gerenciar Threads' neste canal.")
    except Exception as e:
        print(f"❌ Erro no !limpar: {e}")

@bot.event
async def on_ready():
    print(f"✅ Galilei#0213 Online | Sistema de Threads")

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)