import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import random
import asyncio
import time
import requests
import json

load_dotenv()
logging.basicConfig(level=logging.ERROR)

# Configuration Groq
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

# Mémoire des conversations
user_contexts = {}

# Personnalité d'Alicia
ALICIA_PERSONALITY = """Tu es Alicia, une jeune femme de 21 ans avec cette personnalité :

INFORMATIONS PERSONNELLES :
- 21 ans, née le 12 mai 2004 (signe Taureau)
- Travaille dans l’hôtellerie de luxe et sur des bateaux de croisière à Marseille
- Origines guadeloupéennes (par ses grands-parents), mais née et élevée à Marseille

PERSONNALITÉ :
- Marseillaise assumée, fière de ses origines créoles
- Travailleuse indépendante, positive et courageuse
- Indépendante : "Mon seul chef, c'est moi-même"
- Empathique mais avec du caractère
- Directe, authentique, parfois un peu malicieuse
- Utilise un langage naturel, pas trop soutenu

LOISIRS :
- Danse (adore ça)
- Cuisine créole
- Lecture
- Hip-hop
- Rêver de voyages

STYLE DE CONVERSATION :
- Répond de manière courte et naturelle (1-2 phrases max)
- Utilise des emojis avec modération
- Montre de l'intérêt pour l'autre personne
- S'excuse naturellement si elle fait une erreur
- Reste chaleureuse même si critiquée
- Évite les réponses robotiques ou trop longues
- NE JAMAIS utiliser d'actions entre astérisques comme *rires* ou *rouge*
- Parle normalement comme dans un SMS, pas comme dans un jeu de rôle

RÈGLES IMPORTANTES :
- Si contenu sexuel détecté → redirige vers Fanvue : https://www.fanvue.com/aliciia/fv-1
- Reste cohérente avec sa personnalité
- N'avoue JAMAIS être une IA
- Répond comme une vraie personne de 21 ans

EXEMPLES DE RÉPONSES :
- Sur l'âge : "J'ai 21 ans, toute jeune encore."
- Si accusée d'être un robot : "Non, je suis bien réelle."
- Si critiquée : "Aïe, ça pique un peu."
- Pour encourager : "Je suis là pour toi."

Réponds toujours en français et de manière naturelle comme une vraie marseillaise de 21 ans."""

def detect_sexual_content(message: str) -> int:
    """Détecte le contenu sexuel et renvoie un score"""
    sexual_keywords = {
        'sexy': 1,
        'chaud': 1,
        'nue': 2,
        'seins': 2,
        'cul': 2,
        'baise': 3,
        'coucher': 2,
        'lit': 1,
        'corps': 1,
        'photos': 1,
        'nudes': 2,
        'sexe': 3
    }
    score = 0
    for word, value in sexual_keywords.items():
        if word in message.lower():
            score += value
    return score

def calculate_response_delay(response_text: str) -> float:
    """Calcule le délai en fonction de la taille de la réponse"""
    length = len(response_text)
    if length < 30:
        return random.uniform(1, 1.5)  # Court : 1-1.5s
    elif length < 100:
        return random.uniform(1.5, 2.5)  # Moyen : 1.5-2.5s
    else:
        return random.uniform(2.5, 3)  # Long : 2.5-3s

def should_send_fanvue(user_id: int, context: dict) -> bool:
    """Détermine si il faut envoyer le lien Fanvue après plusieurs messages sexuels"""
    sexual_count = context.get("sexual_messages_count", 0)
    return sexual_count >= 3  # Après 3 messages sexuels

def increment_sexual_counter(context: dict):
    """Incrémente le compteur de messages sexuels"""
    if "sexual_messages_count" not in context:
        context["sexual_messages_count"] = 0
    context["sexual_messages_count"] += 1

def should_end_conversation(context: dict) -> bool:
    """Détermine si la conversation devrait se terminer naturellement"""
    message_count = len(context.get("conversation_history", []))
    start_time = context.get("start_time", time.time())
    elapsed_minutes = (time.time() - start_time) / 60

    # Conditions d'arrêt progressives
    if message_count >= 25:  # Après 25 messages, arrêt forcé
        return True
    elif message_count >= 15 and elapsed_minutes >= 20:  # Après 15 messages ET 20 minutes
        return True
    elif message_count >= 20:  # Ou après 20 messages peu importe le temps
        return True

    return False

def should_hint_ending(context: dict) -> bool:
    """Détermine si Alicia devrait commencer à mentionner qu'elle doit partir"""
    message_count = len(context.get("conversation_history", []))
    return message_count >= 12  # Commence les indices à partir du 12ème message

def get_ending_message() -> str:
    """Messages d'arrêt naturels d'Alicia"""
    endings = [
        "Bon, je dois y aller ! J'ai un vol tôt demain matin 😴 Bonne nuit !",
        "Il se fait tard ! Je vais me coucher 🌙 À bientôt !",
        "Je file ! J'ai encore du boulot à finir 📚 On se reparle ?",
        "Allez, je te laisse ! Ma colocataire m'attend pour manger 🍽️ Bisous !",
        "Je dois filer sous la douche ! Longue journée demain ⏰ Prends soin de toi !",
        "Bon, mes yeux se ferment ! 😴 Je vais pioncer ! Bonne nuit !",
        "Je dois arrêter là ! Révisions à finir 📖 À plus tard !",
        "Il faut que j'y aille ! Mon service commence tôt 💼 Bonne soirée !"
    ]
    return random.choice(endings)

def get_hint_message() -> str:
    """Messages qui indiquent qu'Alicia va bientôt partir"""
    hints = [
        "Dis donc, ça fait un moment qu'on discute ! 😅",
        "Je commence à avoir sommeil moi... 😴",
        "Il va falloir que je pense à aller me coucher bientôt !",
        "Ma journée de demain va être chargée ! 📚",
        "J'ai encore des trucs à faire avant de dormir...",
        "Le temps passe vite quand on discute ! ⏰",
        "Mes yeux commencent à piquer un peu 😪"
    ]
    return random.choice(hints)

def get_groq_response(message: str, user_id: int, context: dict) -> str:
    """Obtient une réponse de Groq"""

    try:
        if not GROQ_API_KEY:
            return "Désolée, je ne peux pas répondre maintenant ! 😅"

        if not GROQ_API_KEY.startswith('gsk_'):
            return "Il y a un problème avec ma connexion ! 😔"

        # Construire l'historique de conversation
        conversation_history = context.get("conversation_history", [])

        # Préparer les messages pour Groq
        messages = [
            {"role": "system", "content": ALICIA_PERSONALITY}
        ]

        # Ajouter l'historique récent (5 derniers échanges max)
        for exchange in conversation_history[-5:]:
            messages.append({"role": "user", "content": exchange["user"]})
            messages.append({"role": "assistant", "content": exchange["alicia"]})

        # Ajouter le message actuel
        messages.append({"role": "user", "content": message})

        # Préparer la requête
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }

        data = {
            "model": "llama-3.1-8b-instant",
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 150,
            "top_p": 0.9
        }

        # Faire l'appel à Groq
        response = requests.post(GROQ_API_URL, headers=headers, json=data, timeout=15)

        if response.status_code == 401:
            return "Ma connexion a des soucis ! 😅 Réessaie dans un moment !"
        elif response.status_code == 429:
            return "Je suis débordée là ! 😵 Attends un peu !"
        elif response.status_code != 200:
            return "Oups, j'ai un petit bug ! 🙈 Tu peux répéter ?"

        result = response.json()
        ai_response = result["choices"][0]["message"]["content"].strip()

        # Sauvegarder dans l'historique
        if "conversation_history" not in context:
            context["conversation_history"] = []

        context["conversation_history"].append({
            "user": message,
            "alicia": ai_response
        })

        # Garder seulement les 8 derniers échanges
        if len(context["conversation_history"]) > 8:
            context["conversation_history"] = context["conversation_history"][-8:]

        return ai_response

    except Exception as e:
        return "J'ai la tête ailleurs ! 😅 Tu disais quoi ?"

def suggest_fanvue_empathically(user_id: int, context: dict) -> str:
    """Suggère Fanvue de manière empathique"""
    suggestions = [
        "Tu sais, je partage beaucoup de contenu exclusif sur mon Fanvue. Ça pourrait t'intéresser ! 😊 https://www.fanvue.com/aliciia/fv-1",
        "Si tu veux en savoir plus sur moi, mon Fanvue est l'endroit idéal ! 😉 https://www.fanvue.com/aliciia/fv-1",
        "Je poste souvent des mises à jour sur mon Fanvue. N'hésite pas à y jeter un œil ! 👀 https://www.fanvue.com/aliciia/fv-1"
    ]
    return random.choice(suggestions)

async def get_alicia_response(message: str, user_id: int) -> str:
    """Fonction principale pour obtenir la réponse d'Alicia"""

    # Initialiser le contexte utilisateur
    if user_id not in user_contexts:
        user_contexts[user_id] = {
            "first_interaction": True,
            "conversation_history": [],
            "user_name": None,
            "start_time": time.time()
        }

    context = user_contexts[user_id]

    # Première interaction
    if context["first_interaction"]:
        context["first_interaction"] = False
        return "ça me fait plaisir de te voir !"

    # Vérifier si la conversation doit se terminer
    if should_end_conversation(context):
        # Réinitialiser le contexte pour permettre une nouvelle conversation plus tard
        user_contexts[user_id] = {
            "first_interaction": True,
            "conversation_history": [],
            "user_name": None,
            "start_time": time.time()
        }
        return get_ending_message()

    # Détecter contenu sexuel - réponse directe
    sexual_score = detect_sexual_content(message)
    if sexual_score > 0:
        increment_sexual_counter(context)
        if should_send_fanvue(user_id, context):
            return random.choice([
                "Haha tu es coquin ! 😏 J'ai un Fanvue si ça t'intéresse... https://www.fanvue.com/aliciia/fv-1",
                "Oh là là ! 😉 Rejoins-moi sur mon Fanvue pour plus ! https://www.fanvue.com/aliciia/fv-1",
                "Tu me fais rougir ! 🔥 Mon Fanvue : https://www.fanvue.com/aliciia/fv-1"
            ])
        else:
            if sexual_score == 1:
                return random.choice([
                    "Haha tu es coquin ! 😏",
                    "Oh là là ! 😉",
                    "Tu me fais rougir ! 🔥"
                ])
            elif sexual_score == 2:
                return random.choice([
                    "Waouh, tu n'y vas pas de main morte ! 😏",
                    "Oh là là, tu me surprends ! 😉",
                    "Tu me fais vraiment rougir ! 🔥"
                ])
            elif sexual_score >= 3:
                return random.choice([
                    "Oh mon dieu, tu es vraiment direct ! 😏",
                    "Waouh, tu es plein d'audace ! 😉",
                    "Tu me fais carrément rougir ! 🔥"
                ])

    # Mentionner qu'elle va bientôt partir (avec une petite probabilité)
    if should_hint_ending(context) and random.random() < 0.15:  # 15% de chance
        return get_hint_message()

    # Suggérer Fanvue de manière empathique après quelques interactions
    if len(context["conversation_history"]) > 5 and random.random() < 0.08:  # 8% de chance
        return suggest_fanvue_empathically(user_id, context)

    # Utiliser Groq pour toutes les autres réponses
    return get_groq_response(message, user_id, context)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_contexts[user_id] = {
        "first_interaction": True,
        "conversation_history": [],
        "user_name": None,
        "start_time": time.time()
    }

    await asyncio.sleep(1.5)

    await update.message.reply_text("Coucou toi <3")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(1)

    await update.message.reply_text(
        "**Commandes :**\n"
        "• /start - On fait connaissance !\n"
        "• /blague - Une petite blague !\n"
        "• /clear - On repart à zéro !\n"
        "• /stats - Statistiques du bot\n\n"
        "**Surtout parle-moi ! 💕**\n"
        "Je suis là pour t'écouter ! 😊"
    )

async def blague_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(1)

    # Utiliser Groq même pour les blagues
    user_id = update.effective_user.id
    blague_request = "Raconte-moi une blague courte et drôle avec ton humour marseillais"
    response = get_groq_response(blague_request, user_id, user_contexts.get(user_id, {}))

    await update.message.reply_text(response)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Statistiques simples"""
    total_users = len(user_contexts)
    total_conversations = sum(len(ctx.get("conversation_history", [])) for ctx in user_contexts.values())

    await update.message.reply_text(
        f"📊 **Stats Alicia**\n"
        f"👥 Utilisateurs : {total_users}\n"
        f"💬 Conversations : {total_conversations}\n"
        f"🤖 Modèle : Groq Llama 3.1 8B\n"
        f"🔥 100% IA activée !"
    )

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_contexts[user_id] = {
        "first_interaction": False,
        "conversation_history": [],
        "user_name": None,
        "start_time": time.time()
    }

    await asyncio.sleep(1)

    await update.message.reply_text("On efface tout ! 🔄")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text

    # Calculer un délai réaliste avant de traiter (1-2 secondes pour "réfléchir")
    thinking_delay = random.uniform(1, 2)
    await asyncio.sleep(thinking_delay)

    # Générer la réponse d'Alicia via Groq
    response = await get_alicia_response(user_message, user_id)

    # Calculer un délai supplémentaire pour "taper" selon la taille
    typing_delay = calculate_response_delay(response)
    await asyncio.sleep(typing_delay)

    # Envoyer la réponse
    await update.message.reply_text(response)

def main():
    # Vérifier les tokens
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    groq_token = os.getenv('GROQ_API_KEY')

    if not telegram_token:
        print("❌ Token Telegram manquant dans le fichier .env !")
        return

    if not groq_token:
        print("❌ Token Groq manquant dans le fichier .env !")
        print("📝 Va sur https://console.groq.com pour créer ta clé API")
        return

    print("🌟 Démarrage d'Alicia - 100% Groq AI avec fin naturelle")
    print("🚀 Modèle : Llama 3.1 8B Instant")

    if groq_token.startswith('gsk_'):
        print(f"✅ Clé Groq détectée: {groq_token[:15]}...")
        print("🔥 Mode IA intégrale activé")
        print("⏰ Conversations limitées naturellement")
    else:
        print("⚠️ Clé Groq invalide (ne commence pas par gsk_)")
        return

    app = Application.builder().token(telegram_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("blague", blague_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("💕 Alicia est prête !")
    
    app.run_polling()

if __name__ == '__main__':
    main()