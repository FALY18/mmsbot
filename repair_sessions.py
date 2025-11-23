#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import time
import random
import json
import subprocess
from instagrapi import Client as InstaClient

def load_accounts():
    """Charge les comptes Instagram"""
    try:
        with open("insta_info.json", "r") as f:
            return json.load(f)
    except:
        print("❌ Fichier insta_info.json introuvable")
        return []

def rotate_ip_advanced():
    """Tente différentes méthodes pour changer l'IP"""
    print("🔧 Tentative de rotation IP avancée...")
    
    methods = [
        # Méthode 1: WiFi
        (["termux-wifi-enable", "false"], ["termux-wifi-enable", "true"]),
        # Méthode 2: Mode avion (simulé)
        (["termux-wifi-enable", "false"], ["termux-wifi-enable", "true"]),
    ]
    
    for disable_cmd, enable_cmd in methods:
        try:
            print(f"🔄 Essai méthode: {disable_cmd[0]}")
            subprocess.run(disable_cmd, timeout=10)
            time.sleep(8)
            subprocess.run(enable_cmd, timeout=10)
            time.sleep(15)
            print("✅ Rotation IP réussie")
            return True
        except Exception as e:
            print(f"❌ Échec: {e}")
            continue
    
    # Méthode de dernier recours: longue attente
    wait_time = random.randint(600, 1200)  # 10-20 minutes
    print(f"⏳ Longue attente de {wait_time//60} minutes...")
    time.sleep(wait_time)
    return True

def clean_session_files():
    """Nettoie les fichiers de session problématiques"""
    session_files = [f for f in os.listdir(".") if f.startswith("session_") and f.endswith(".json")]
    
    for session_file in session_files:
        try:
            os.remove(session_file)
            print(f"🗑️ Supprimé: {session_file}")
        except Exception as e:
            print(f"⚠️ Impossible de supprimer {session_file}: {e}")

def test_instagram_connection(username, password):
    """Teste la connexion à Instagram"""
    print(f"🔗 Test de connexion pour {username}...")
    
    cl = InstaClient()
    try:
        # Configuration aléatoire
        devices = [
            {
                "app_version": "200.0.0.30.128",
                "android_version": 26,
                "android_release": "8.0.0",
                "dpi": "480dpi",
                "resolution": "1080x1920",
                "manufacturer": "samsung",
                "device": "SM-G935F",
                "model": "herolte",
                "cpu": "samsungexynos8890"
            },
            {
                "app_version": "200.0.0.30.128",
                "android_version": 29,
                "android_release": "10.0.0",
                "dpi": "420dpi",
                "resolution": "1080x2280",
                "manufacturer": "google", 
                "device": "Pixel 4",
                "model": "pixel4",
                "cpu": "qualcomm"
            }
        ]
        
        cl.set_device(random.choice(devices))
        cl.login(username, password)
        
        # Test simple
        user_info = cl.account_info()
        print(f"✅ Connexion réussie pour {username}")
        print(f"   Followers: {user_info.follower_count}")
        
        cl.dump_settings(f"session_{username}.json")
        return True
        
    except Exception as e:
        print(f"❌ Échec connexion pour {username}: {e}")
        return False

def main():
    """Fonction principale de réparation"""
    print("🛠️ DÉMARRAGE RÉPARATION SESSIONS INSTAGRAM")
    print("=" * 50)
    
    accounts = load_accounts()
    if not accounts:
        return
    
    # Étape 1: Nettoyage
    print("\n1. 🗑️ NETTOYAGE DES SESSIONS")
    clean_session_files()
    
    # Étape 2: Rotation IP
    print("\n2. 🔄 ROTATION IP")
    rotate_ip_advanced()
    
    # Étape 3: Test des connexions
    print("\n3. 🔗 TEST DES CONNEXIONS")
    successful = 0
    
    for account in accounts:
        username = account["username"]
        password = account["password"]
        
        if test_instagram_connection(username, password):
            successful += 1
        
        # Délai entre les tests
        if successful < len(accounts):
            delay = random.randint(30, 60)
            print(f"⏳ Attente de {delay}s...")
            time.sleep(delay)
    
    print(f"\n📊 RÉSULTATS: {successful}/{len(accounts)} comptes réparés")
    
    if successful > 0:
        print("✅ Réparation terminée avec succès!")
        print("🎯 Vous pouvez maintenant relancer le bot principal")
    else:
        print("❌ Aucun compte n'a pu être réparé")
        print("💡 Suggestions:")
        print("   - Attendez 24 heures")
        print("   - Changez de réseau (WiFi différent)")
        print("   - Utilisez un VPN")

if __name__ == "__main__":
    main()