#!/usr/bin/env python3
"""auto-enrich-glycemic.py — Génère un patch data-glycemic pour les
ingrédients manquants détectés par lint-new-recipes.py.

Usage :
    python3 scripts/auto-enrich-glycemic.py /tmp/lot65-recipes.py
    python3 scripts/auto-enrich-glycemic.py /tmp/lot65.py --apply
    python3 scripts/auto-enrich-glycemic.py --names "salade romaine,asperges vertes,dattes medjool"

Sources nutritionnelles (mini-DB embarquée, ~250 ingrédients) :
    - CIQUAL ANSES 2020 (base française officielle)
    - USDA FoodData Central (compléments hors EU)
    - GIF Sydney + Harvard School of Public Health (IG)

3 niveaux de confiance fuzzy matching (difflib) :
    >= 95%  → auto-ajouté à data-glycemic
    70-94%  → proposé pour validation manuelle (interactive)
    < 70%   → marqué "à compléter manuellement"
"""

import sys
import re
import json
import argparse
import unicodedata
import difflib
from pathlib import Path
from importlib import util as importlib_util

RESET = "\033[0m"; RED = "\033[91m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
BLUE = "\033[94m"; CYAN = "\033[96m"; BOLD = "\033[1m"; DIM = "\033[2m"

# ────────────────────────── MINI-DB CIQUAL / USDA ──────────────────────────
# Format : {id_canonique: {ig, carbsPer100g, proteinPer100g, fatPer100g}}
# IG : 0 pour épices/aromates (négligeable nutritionnellement).
# Sources : CIQUAL 2020, USDA FoodData Central, GIF Sydney, Harvard.
MINI_DB = {
    # ----- LÉGUMES (vraies racines absents) -----
    "salade romaine":       {"ig": 15, "carbsPer100g": 3.3,  "proteinPer100g": 1.2,  "fatPer100g": 0.3},
    "salade iceberg":       {"ig": 15, "carbsPer100g": 3.0,  "proteinPer100g": 0.9,  "fatPer100g": 0.1},
    "salade roquette":      {"ig": 15, "carbsPer100g": 3.7,  "proteinPer100g": 2.6,  "fatPer100g": 0.7},
    "pousses d'epinards":   {"ig": 15, "carbsPer100g": 3.6,  "proteinPer100g": 2.9,  "fatPer100g": 0.4},
    "asperges vertes":      {"ig": 15, "carbsPer100g": 3.9,  "proteinPer100g": 2.2,  "fatPer100g": 0.1},
    "asperges":             {"ig": 15, "carbsPer100g": 3.9,  "proteinPer100g": 2.2,  "fatPer100g": 0.1},
    "haricots verts":       {"ig": 15, "carbsPer100g": 7.0,  "proteinPer100g": 1.8,  "fatPer100g": 0.2},
    "petits pois frais":    {"ig": 35, "carbsPer100g": 14.0, "proteinPer100g": 5.4,  "fatPer100g": 0.4},
    "petits pois":          {"ig": 35, "carbsPer100g": 14.0, "proteinPer100g": 5.4,  "fatPer100g": 0.4},
    "radis":                {"ig": 15, "carbsPer100g": 3.4,  "proteinPer100g": 0.7,  "fatPer100g": 0.1},
    "radis rose":           {"ig": 15, "carbsPer100g": 3.4,  "proteinPer100g": 0.7,  "fatPer100g": 0.1},
    "mais en grains":       {"ig": 65, "carbsPer100g": 19.0, "proteinPer100g": 3.3,  "fatPer100g": 1.4},
    "mais":                 {"ig": 65, "carbsPer100g": 19.0, "proteinPer100g": 3.3,  "fatPer100g": 1.4},
    "champignon de paris":  {"ig": 15, "carbsPer100g": 3.3,  "proteinPer100g": 3.1,  "fatPer100g": 0.3},
    "champignon shiitake":  {"ig": 15, "carbsPer100g": 7.0,  "proteinPer100g": 2.2,  "fatPer100g": 0.5},
    "champignon noir":      {"ig": 15, "carbsPer100g": 7.0,  "proteinPer100g": 4.9,  "fatPer100g": 0.5},
    "betterave rouge cuite": {"ig": 64, "carbsPer100g": 10.0, "proteinPer100g": 1.7, "fatPer100g": 0.2},
    "betterave":            {"ig": 64, "carbsPer100g": 10.0, "proteinPer100g": 1.7,  "fatPer100g": 0.2},
    "concombre":            {"ig": 15, "carbsPer100g": 3.6,  "proteinPer100g": 0.7,  "fatPer100g": 0.1},
    "celeri":               {"ig": 15, "carbsPer100g": 3.0,  "proteinPer100g": 0.7,  "fatPer100g": 0.2},
    "poireau":              {"ig": 32, "carbsPer100g": 14.0, "proteinPer100g": 1.5,  "fatPer100g": 0.3},
    "courgette":            {"ig": 15, "carbsPer100g": 3.1,  "proteinPer100g": 1.2,  "fatPer100g": 0.3},
    "aubergine":            {"ig": 20, "carbsPer100g": 5.9,  "proteinPer100g": 1.0,  "fatPer100g": 0.2},
    "poivron rouge":        {"ig": 15, "carbsPer100g": 6.0,  "proteinPer100g": 1.0,  "fatPer100g": 0.3},
    "poivron jaune":        {"ig": 15, "carbsPer100g": 6.3,  "proteinPer100g": 1.0,  "fatPer100g": 0.2},
    "poivron vert":         {"ig": 15, "carbsPer100g": 4.6,  "proteinPer100g": 0.9,  "fatPer100g": 0.2},
    "chou rouge":           {"ig": 15, "carbsPer100g": 7.4,  "proteinPer100g": 1.4,  "fatPer100g": 0.2},
    "chou chinois":         {"ig": 15, "carbsPer100g": 2.2,  "proteinPer100g": 1.5,  "fatPer100g": 0.2},
    "chou-fleur":           {"ig": 15, "carbsPer100g": 5.0,  "proteinPer100g": 1.9,  "fatPer100g": 0.3},
    "brocoli":              {"ig": 15, "carbsPer100g": 7.0,  "proteinPer100g": 2.8,  "fatPer100g": 0.4},
    "fenouil":              {"ig": 15, "carbsPer100g": 7.3,  "proteinPer100g": 1.2,  "fatPer100g": 0.2},
    "endive":               {"ig": 15, "carbsPer100g": 4.0,  "proteinPer100g": 0.9,  "fatPer100g": 0.1},
    "navet":                {"ig": 30, "carbsPer100g": 6.4,  "proteinPer100g": 0.9,  "fatPer100g": 0.1},
    "panais":               {"ig": 52, "carbsPer100g": 18.0, "proteinPer100g": 1.2,  "fatPer100g": 0.3},
    "topinambour":          {"ig": 50, "carbsPer100g": 17.0, "proteinPer100g": 2.0,  "fatPer100g": 0.0},
    # ----- FRUITS -----
    "fraise fraiche":       {"ig": 25, "carbsPer100g": 7.7,  "proteinPer100g": 0.7,  "fatPer100g": 0.3},
    "framboise":            {"ig": 25, "carbsPer100g": 11.0, "proteinPer100g": 1.2,  "fatPer100g": 0.7},
    "myrtille":             {"ig": 25, "carbsPer100g": 14.0, "proteinPer100g": 0.7,  "fatPer100g": 0.3},
    "mure":                 {"ig": 25, "carbsPer100g": 9.6,  "proteinPer100g": 1.4,  "fatPer100g": 0.5},
    "grenade":              {"ig": 35, "carbsPer100g": 19.0, "proteinPer100g": 1.7,  "fatPer100g": 1.2},
    "datte medjool":        {"ig": 42, "carbsPer100g": 75.0, "proteinPer100g": 1.8,  "fatPer100g": 0.2},
    "datte":                {"ig": 42, "carbsPer100g": 75.0, "proteinPer100g": 1.8,  "fatPer100g": 0.2},
    "raisin":               {"ig": 55, "carbsPer100g": 17.0, "proteinPer100g": 0.7,  "fatPer100g": 0.2},
    "raisin sec":           {"ig": 65, "carbsPer100g": 79.0, "proteinPer100g": 3.1,  "fatPer100g": 0.5},
    "figue fraiche":        {"ig": 35, "carbsPer100g": 19.0, "proteinPer100g": 0.8,  "fatPer100g": 0.3},
    "figue seche":          {"ig": 40, "carbsPer100g": 64.0, "proteinPer100g": 3.3,  "fatPer100g": 0.9},
    "abricot":              {"ig": 30, "carbsPer100g": 11.0, "proteinPer100g": 1.4,  "fatPer100g": 0.4},
    "abricot sec":          {"ig": 40, "carbsPer100g": 63.0, "proteinPer100g": 3.4,  "fatPer100g": 0.5},
    "peche":                {"ig": 42, "carbsPer100g": 10.0, "proteinPer100g": 0.9,  "fatPer100g": 0.2},
    "peche blanche":        {"ig": 42, "carbsPer100g": 10.0, "proteinPer100g": 0.9,  "fatPer100g": 0.2},
    "nectarine":            {"ig": 35, "carbsPer100g": 10.0, "proteinPer100g": 1.1,  "fatPer100g": 0.3},
    "pomme verte":          {"ig": 35, "carbsPer100g": 14.0, "proteinPer100g": 0.3,  "fatPer100g": 0.2},
    "poire":                {"ig": 38, "carbsPer100g": 15.0, "proteinPer100g": 0.4,  "fatPer100g": 0.1},
    "kiwi":                 {"ig": 50, "carbsPer100g": 14.0, "proteinPer100g": 1.1,  "fatPer100g": 0.5},
    "ananas":               {"ig": 59, "carbsPer100g": 13.0, "proteinPer100g": 0.5,  "fatPer100g": 0.1},
    "ananas frais":         {"ig": 59, "carbsPer100g": 13.0, "proteinPer100g": 0.5,  "fatPer100g": 0.1},
    "pasteque":             {"ig": 75, "carbsPer100g": 8.0,  "proteinPer100g": 0.6,  "fatPer100g": 0.2},
    "melon":                {"ig": 65, "carbsPer100g": 9.0,  "proteinPer100g": 0.8,  "fatPer100g": 0.2},
    "papaye":               {"ig": 60, "carbsPer100g": 11.0, "proteinPer100g": 0.5,  "fatPer100g": 0.3},
    "pomelo":               {"ig": 25, "carbsPer100g": 9.0,  "proteinPer100g": 0.8,  "fatPer100g": 0.0},
    "pamplemousse rose":    {"ig": 25, "carbsPer100g": 9.0,  "proteinPer100g": 0.8,  "fatPer100g": 0.1},
    "litchi":               {"ig": 50, "carbsPer100g": 17.0, "proteinPer100g": 0.8,  "fatPer100g": 0.4},
    "fruit de la passion":  {"ig": 30, "carbsPer100g": 23.0, "proteinPer100g": 2.2,  "fatPer100g": 0.7},
    "mandarine":            {"ig": 35, "carbsPer100g": 13.0, "proteinPer100g": 0.8,  "fatPer100g": 0.3},
    "clementine":           {"ig": 35, "carbsPer100g": 12.0, "proteinPer100g": 0.9,  "fatPer100g": 0.2},
    "orange sanguine":      {"ig": 35, "carbsPer100g": 12.0, "proteinPer100g": 0.9,  "fatPer100g": 0.1},
    "fruits rouges":        {"ig": 25, "carbsPer100g": 10.0, "proteinPer100g": 1.0,  "fatPer100g": 0.4},
    "fruits exotiques":     {"ig": 50, "carbsPer100g": 14.0, "proteinPer100g": 0.8,  "fatPer100g": 0.3},
    "pruneau":              {"ig": 40, "carbsPer100g": 64.0, "proteinPer100g": 2.2,  "fatPer100g": 0.4},
    "pruneau denoyaute":    {"ig": 40, "carbsPer100g": 64.0, "proteinPer100g": 2.2,  "fatPer100g": 0.4},
    "cerise":               {"ig": 25, "carbsPer100g": 15.0, "proteinPer100g": 1.0,  "fatPer100g": 0.3},
    "cerise noire":         {"ig": 25, "carbsPer100g": 15.0, "proteinPer100g": 1.0,  "fatPer100g": 0.3},
    # ----- LÉGUMINEUSES -----
    "lentilles vertes":     {"ig": 30, "carbsPer100g": 20.0, "proteinPer100g": 9.0,  "fatPer100g": 0.4},
    "lentilles vertes du puy": {"ig": 30, "carbsPer100g": 20.0, "proteinPer100g": 9.0, "fatPer100g": 0.4},
    "lentilles brunes":     {"ig": 30, "carbsPer100g": 20.0, "proteinPer100g": 9.0,  "fatPer100g": 0.4},
    "feves sec":            {"ig": 25, "carbsPer100g": 58.0, "proteinPer100g": 26.0, "fatPer100g": 1.5},
    "feves":                {"ig": 40, "carbsPer100g": 7.5,  "proteinPer100g": 5.5,  "fatPer100g": 0.6},
    "feves seches decortiquees": {"ig": 25, "carbsPer100g": 58.0, "proteinPer100g": 26.0, "fatPer100g": 1.5},
    "chana dal":            {"ig": 28, "carbsPer100g": 27.0, "proteinPer100g": 8.9,  "fatPer100g": 2.6},
    "haricot rouge":        {"ig": 35, "carbsPer100g": 23.0, "proteinPer100g": 8.7,  "fatPer100g": 0.5},
    "haricot blanc":        {"ig": 31, "carbsPer100g": 20.0, "proteinPer100g": 7.7,  "fatPer100g": 0.5},
    "haricot noir":         {"ig": 30, "carbsPer100g": 24.0, "proteinPer100g": 8.9,  "fatPer100g": 0.5},
    "haricots noirs cuits": {"ig": 30, "carbsPer100g": 24.0, "proteinPer100g": 8.9,  "fatPer100g": 0.5},
    "haricots blancs cuits":{"ig": 31, "carbsPer100g": 20.0, "proteinPer100g": 7.7,  "fatPer100g": 0.5},
    "haricots rouges cuits":{"ig": 35, "carbsPer100g": 23.0, "proteinPer100g": 8.7,  "fatPer100g": 0.5},
    "edamame ecosses":      {"ig": 18, "carbsPer100g": 9.9,  "proteinPer100g": 11.0, "fatPer100g": 5.0},
    "edamame":              {"ig": 18, "carbsPer100g": 9.9,  "proteinPer100g": 11.0, "fatPer100g": 5.0},
    # ----- OLÉAGINEUX / GRAINES -----
    "amande":               {"ig": 15, "carbsPer100g": 21.0, "proteinPer100g": 21.0, "fatPer100g": 49.0},
    "amandes":              {"ig": 15, "carbsPer100g": 21.0, "proteinPer100g": 21.0, "fatPer100g": 49.0},
    "amande entiere":       {"ig": 15, "carbsPer100g": 21.0, "proteinPer100g": 21.0, "fatPer100g": 49.0},
    "noix":                 {"ig": 15, "carbsPer100g": 14.0, "proteinPer100g": 15.0, "fatPer100g": 65.0},
    "noisette":             {"ig": 15, "carbsPer100g": 17.0, "proteinPer100g": 15.0, "fatPer100g": 61.0},
    "noix de cajou":        {"ig": 22, "carbsPer100g": 30.0, "proteinPer100g": 18.0, "fatPer100g": 44.0},
    "noix de pecan":        {"ig": 10, "carbsPer100g": 14.0, "proteinPer100g": 9.0,  "fatPer100g": 72.0},
    "pignons de pin":       {"ig": 15, "carbsPer100g": 13.0, "proteinPer100g": 14.0, "fatPer100g": 68.0},
    "graines de courge":    {"ig": 25, "carbsPer100g": 11.0, "proteinPer100g": 30.0, "fatPer100g": 49.0},
    "graines de lin":       {"ig": 35, "carbsPer100g": 29.0, "proteinPer100g": 18.0, "fatPer100g": 42.0},
    "beurre d'amande":      {"ig": 25, "carbsPer100g": 19.0, "proteinPer100g": 21.0, "fatPer100g": 56.0},
    "beurre de cacahuete":  {"ig": 14, "carbsPer100g": 20.0, "proteinPer100g": 25.0, "fatPer100g": 50.0},
    "purée d'amande":       {"ig": 25, "carbsPer100g": 12.0, "proteinPer100g": 21.0, "fatPer100g": 56.0},
    "cacahuete grillee":    {"ig": 14, "carbsPer100g": 16.0, "proteinPer100g": 26.0, "fatPer100g": 49.0},
    "noix de coco rapee":   {"ig": 45, "carbsPer100g": 24.0, "proteinPer100g": 7.0,  "fatPer100g": 65.0},
    # ----- CÉRÉALES / FÉCULENTS -----
    "polenta":              {"ig": 68, "carbsPer100g": 78.0, "proteinPer100g": 8.0,  "fatPer100g": 1.2},
    "polenta fine":         {"ig": 68, "carbsPer100g": 78.0, "proteinPer100g": 8.0,  "fatPer100g": 1.2},
    "perles de tapioca":    {"ig": 70, "carbsPer100g": 88.0, "proteinPer100g": 0.2,  "fatPer100g": 0.0},
    "tapioca":              {"ig": 70, "carbsPer100g": 88.0, "proteinPer100g": 0.2,  "fatPer100g": 0.0},
    "boulgour complet":     {"ig": 48, "carbsPer100g": 19.0, "proteinPer100g": 3.1,  "fatPer100g": 0.2},
    "boulgour fin":         {"ig": 48, "carbsPer100g": 19.0, "proteinPer100g": 3.1,  "fatPer100g": 0.2},
    "vermicelle":           {"ig": 50, "carbsPer100g": 75.0, "proteinPer100g": 12.0, "fatPer100g": 1.0},
    "vermicelles de soja":  {"ig": 39, "carbsPer100g": 86.0, "proteinPer100g": 0.2,  "fatPer100g": 0.0},
    "nouilles soba":        {"ig": 46, "carbsPer100g": 25.0, "proteinPer100g": 5.0,  "fatPer100g": 0.1},
    "riz aplati poha":      {"ig": 35, "carbsPer100g": 80.0, "proteinPer100g": 6.6,  "fatPer100g": 1.2},
    "riz noir":             {"ig": 42, "carbsPer100g": 23.0, "proteinPer100g": 4.0,  "fatPer100g": 1.8},
    "riz long complet":     {"ig": 50, "carbsPer100g": 28.0, "proteinPer100g": 3.0,  "fatPer100g": 0.7},
    "farine de riz":        {"ig": 95, "carbsPer100g": 80.0, "proteinPer100g": 6.0,  "fatPer100g": 1.4},
    "farine de mais":       {"ig": 70, "carbsPer100g": 76.0, "proteinPer100g": 7.0,  "fatPer100g": 3.9},
    "farine de chataigne":  {"ig": 65, "carbsPer100g": 78.0, "proteinPer100g": 6.0,  "fatPer100g": 3.0},
    "biscuit cuillere":     {"ig": 60, "carbsPer100g": 72.0, "proteinPer100g": 8.5,  "fatPer100g": 3.0},
    "boudoir":              {"ig": 60, "carbsPer100g": 72.0, "proteinPer100g": 8.5,  "fatPer100g": 3.0},
    "pita complet":         {"ig": 53, "carbsPer100g": 55.0, "proteinPer100g": 11.0, "fatPer100g": 2.5},
    "tortilla de mais":     {"ig": 52, "carbsPer100g": 45.0, "proteinPer100g": 6.0,  "fatPer100g": 3.0},
    "tortilla de ble complet":{"ig":53,"carbsPer100g": 55.0, "proteinPer100g": 9.0,  "fatPer100g": 4.0},
    "pain pita complet":    {"ig": 53, "carbsPer100g": 55.0, "proteinPer100g": 11.0, "fatPer100g": 2.5},
    "feuille de brick":     {"ig": 70, "carbsPer100g": 65.0, "proteinPer100g": 9.0,  "fatPer100g": 1.0},
    "pate filo":            {"ig": 70, "carbsPer100g": 65.0, "proteinPer100g": 9.0,  "fatPer100g": 1.0},
    "galette de riz":       {"ig": 85, "carbsPer100g": 82.0, "proteinPer100g": 7.5,  "fatPer100g": 1.0},
    "galette spring roll":  {"ig": 75, "carbsPer100g": 82.0, "proteinPer100g": 7.0,  "fatPer100g": 0.5},
    "galette gyoza":        {"ig": 65, "carbsPer100g": 56.0, "proteinPer100g": 10.0, "fatPer100g": 1.5},
    "pate brick":           {"ig": 70, "carbsPer100g": 65.0, "proteinPer100g": 9.0,  "fatPer100g": 1.0},
    "semoule fine":         {"ig": 60, "carbsPer100g": 73.0, "proteinPer100g": 13.0, "fatPer100g": 1.0},
    "couscous complet":     {"ig": 45, "carbsPer100g": 70.0, "proteinPer100g": 12.0, "fatPer100g": 1.5},
    "flocons d'avoine complets": {"ig": 40, "carbsPer100g": 60.0, "proteinPer100g": 13.0, "fatPer100g": 7.0},
    "millet":               {"ig": 71, "carbsPer100g": 73.0, "proteinPer100g": 11.0, "fatPer100g": 4.2},
    "epeautre":             {"ig": 45, "carbsPer100g": 70.0, "proteinPer100g": 15.0, "fatPer100g": 2.4},
    "orge perle":           {"ig": 25, "carbsPer100g": 73.0, "proteinPer100g": 10.0, "fatPer100g": 1.2},
    # ----- VIANDES / POISSONS -----
    "poulet haché":         {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 20.0, "fatPer100g": 9.0},
    "magret de canard":     {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 17.0, "fatPer100g": 18.0},
    "rumsteck":             {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 26.0, "fatPer100g": 8.0},
    "agneau (gigot)":       {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 21.0, "fatPer100g": 12.0},
    "lardons fumes":        {"ig": 0,  "carbsPer100g": 0.5,  "proteinPer100g": 17.0, "fatPer100g": 28.0},
    "jambon blanc":         {"ig": 0,  "carbsPer100g": 0.5,  "proteinPer100g": 21.0, "fatPer100g": 3.0},
    "saumon frais":         {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 20.0, "fatPer100g": 13.0},
    "saumon fume":          {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 22.0, "fatPer100g": 12.0},
    "thon naturel en boite":{"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 26.0, "fatPer100g": 0.9},
    "sardine en boite":     {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 25.0, "fatPer100g": 11.0},
    "maquereau":            {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 19.0, "fatPer100g": 14.0},
    "cabillaud":            {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 18.0, "fatPer100g": 0.7},
    "crevette decortiquee": {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 22.0, "fatPer100g": 1.0},
    # ----- LAITAGES / TOFU -----
    "tofu ferme":           {"ig": 15, "carbsPer100g": 1.9,  "proteinPer100g": 17.0, "fatPer100g": 9.0},
    "tofu soyeux":          {"ig": 15, "carbsPer100g": 2.0,  "proteinPer100g": 5.0,  "fatPer100g": 3.0},
    "tofu":                 {"ig": 15, "carbsPer100g": 1.9,  "proteinPer100g": 13.0, "fatPer100g": 6.0},
    "tempeh":               {"ig": 15, "carbsPer100g": 9.0,  "proteinPer100g": 19.0, "fatPer100g": 11.0},
    "mozzarella":           {"ig": 27, "carbsPer100g": 2.2,  "proteinPer100g": 22.0, "fatPer100g": 22.0},
    "mozzarella di bufala": {"ig": 27, "carbsPer100g": 0.5,  "proteinPer100g": 17.0, "fatPer100g": 24.0},
    "burrata":              {"ig": 27, "carbsPer100g": 1.0,  "proteinPer100g": 14.0, "fatPer100g": 26.0},
    "ricotta":              {"ig": 27, "carbsPer100g": 3.0,  "proteinPer100g": 11.0, "fatPer100g": 13.0},
    "mascarpone":           {"ig": 27, "carbsPer100g": 4.5,  "proteinPer100g": 4.4,  "fatPer100g": 42.0},
    "feta":                 {"ig": 27, "carbsPer100g": 4.0,  "proteinPer100g": 14.0, "fatPer100g": 21.0},
    "chevre frais":         {"ig": 27, "carbsPer100g": 4.0,  "proteinPer100g": 6.0,  "fatPer100g": 15.0},
    "fromage frais":        {"ig": 27, "carbsPer100g": 4.0,  "proteinPer100g": 8.0,  "fatPer100g": 5.0},
    "parmesan":             {"ig": 27, "carbsPer100g": 0,    "proteinPer100g": 36.0, "fatPer100g": 28.0},
    "comte":                {"ig": 27, "carbsPer100g": 1.5,  "proteinPer100g": 28.0, "fatPer100g": 34.0},
    "emmental":             {"ig": 27, "carbsPer100g": 1.0,  "proteinPer100g": 29.0, "fatPer100g": 28.0},
    "cheddar":              {"ig": 27, "carbsPer100g": 1.3,  "proteinPer100g": 25.0, "fatPer100g": 33.0},
    "creme liquide":        {"ig": 30, "carbsPer100g": 3.1,  "proteinPer100g": 2.5,  "fatPer100g": 35.0},
    "creme liquide entiere":{"ig": 30, "carbsPer100g": 3.1,  "proteinPer100g": 2.5,  "fatPer100g": 35.0},
    "creme fraiche epaisse": {"ig":30, "carbsPer100g": 3.5,  "proteinPer100g": 2.5,  "fatPer100g": 30.0},
    "yaourt nature":        {"ig": 35, "carbsPer100g": 4.7,  "proteinPer100g": 4.0,  "fatPer100g": 1.5},
    "yaourt grec":          {"ig": 11, "carbsPer100g": 4.0,  "proteinPer100g": 9.0,  "fatPer100g": 5.0},
    "fromage blanc":        {"ig": 30, "carbsPer100g": 4.0,  "proteinPer100g": 8.0,  "fatPer100g": 0.5},
    "fromage blanc 0%":     {"ig": 30, "carbsPer100g": 4.5,  "proteinPer100g": 7.5,  "fatPer100g": 0.2},
    # ----- HUILES / GRAS / CONDIMENTS -----
    "miel d'acacia":        {"ig": 35, "carbsPer100g": 75.0, "proteinPer100g": 0.4,  "fatPer100g": 0.0},
    "miel de thym":         {"ig": 55, "carbsPer100g": 75.0, "proteinPer100g": 0.4,  "fatPer100g": 0.0},
    "miel d'oranger":       {"ig": 55, "carbsPer100g": 75.0, "proteinPer100g": 0.4,  "fatPer100g": 0.0},
    "sirop d'erable":       {"ig": 54, "carbsPer100g": 67.0, "proteinPer100g": 0.0,  "fatPer100g": 0.1},
    "sirop d'agave":        {"ig": 19, "carbsPer100g": 76.0, "proteinPer100g": 0.0,  "fatPer100g": 0.4},
    "sucre de coco":        {"ig": 35, "carbsPer100g": 100.0, "proteinPer100g": 0.0, "fatPer100g": 0.0},
    "ghee":                 {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 0,    "fatPer100g": 99.0},
    "beurre clarifie":      {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 0,    "fatPer100g": 99.0},
    "huile d'argan":        {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 0,    "fatPer100g": 100.0},
    "huile de noix":        {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 0,    "fatPer100g": 100.0},
    # ----- SAUCES / CONDIMENTS LIQUIDES -----
    "sauce soja legere":    {"ig": 0,  "carbsPer100g": 5.5,  "proteinPer100g": 7.0,  "fatPer100g": 0.1},
    "mirin":                {"ig": 35, "carbsPer100g": 43.0, "proteinPer100g": 0.2,  "fatPer100g": 0.0},
    "sauce nuoc-mam":       {"ig": 0,  "carbsPer100g": 4.0,  "proteinPer100g": 5.0,  "fatPer100g": 0.0},
    "mayonnaise allegee":   {"ig": 0,  "carbsPer100g": 5.0,  "proteinPer100g": 0.4,  "fatPer100g": 30.0},
    "moutarde de dijon":    {"ig": 35, "carbsPer100g": 4.0,  "proteinPer100g": 7.7,  "fatPer100g": 4.4},
    "vinaigre de cidre":    {"ig": 0,  "carbsPer100g": 0.9,  "proteinPer100g": 0.0,  "fatPer100g": 0.0},
    "vinaigre balsamique":  {"ig": 30, "carbsPer100g": 17.0, "proteinPer100g": 0.5,  "fatPer100g": 0.0},
    "tahin":                {"ig": 40, "carbsPer100g": 21.0, "proteinPer100g": 17.0, "fatPer100g": 54.0},
    "purée de sésame":      {"ig": 40, "carbsPer100g": 21.0, "proteinPer100g": 17.0, "fatPer100g": 54.0},
    "pate de sesame noir":  {"ig": 40, "carbsPer100g": 21.0, "proteinPer100g": 17.0, "fatPer100g": 54.0},
    "pate de tamarin":      {"ig": 0,  "carbsPer100g": 60.0, "proteinPer100g": 2.8,  "fatPer100g": 0.6},
    "harissa":              {"ig": 30, "carbsPer100g": 17.0, "proteinPer100g": 2.0,  "fatPer100g": 8.0},
    "pate de curry":        {"ig": 0,  "carbsPer100g": 24.0, "proteinPer100g": 4.0,  "fatPer100g": 10.0},
    "rhum brun":            {"ig": 0,  "carbsPer100g": 0.4,  "proteinPer100g": 0.0,  "fatPer100g": 0.0},
    "cafe":                 {"ig": 0,  "carbsPer100g": 0.5,  "proteinPer100g": 0.1,  "fatPer100g": 0.0},
    "the matcha":           {"ig": 0,  "carbsPer100g": 39.0, "proteinPer100g": 30.0, "fatPer100g": 5.0},
    "the vert":             {"ig": 0,  "carbsPer100g": 0.5,  "proteinPer100g": 0.0,  "fatPer100g": 0.0},
    # ----- ÉPICES / MÉLANGES (impact nutri faible mais souvent cités) -----
    "ras el hanout":        {"ig": 0,  "carbsPer100g": 49.0, "proteinPer100g": 11.0, "fatPer100g": 10.0},
    "garam masala":         {"ig": 0,  "carbsPer100g": 50.0, "proteinPer100g": 10.0, "fatPer100g": 15.0},
    "curry doux":           {"ig": 0,  "carbsPer100g": 56.0, "proteinPer100g": 14.0, "fatPer100g": 14.0},
    "curry":                {"ig": 0,  "carbsPer100g": 56.0, "proteinPer100g": 14.0, "fatPer100g": 14.0},
    "chaat masala":         {"ig": 0,  "carbsPer100g": 50.0, "proteinPer100g": 10.0, "fatPer100g": 5.0},
    "5 epices chinoises":   {"ig": 0,  "carbsPer100g": 60.0, "proteinPer100g": 11.0, "fatPer100g": 10.0},
    "epices":               {"ig": 0,  "carbsPer100g": 50.0, "proteinPer100g": 10.0, "fatPer100g": 10.0},
    "graines de moutarde":  {"ig": 0,  "carbsPer100g": 28.0, "proteinPer100g": 27.0, "fatPer100g": 36.0},
    "anis vert":            {"ig": 0,  "carbsPer100g": 50.0, "proteinPer100g": 18.0, "fatPer100g": 16.0},
    "feuilles de curry":    {"ig": 0,  "carbsPer100g": 12.0, "proteinPer100g": 6.0,  "fatPer100g": 1.0},
    "zeste de citron":      {"ig": 0,  "carbsPer100g": 16.0, "proteinPer100g": 1.5,  "fatPer100g": 0.3},
    "zeste de citron vert": {"ig": 0,  "carbsPer100g": 16.0, "proteinPer100g": 1.5,  "fatPer100g": 0.3},
    # ----- BOUILLONS / EAUX (impact négligeable mais courants) -----
    "bouillon de legumes":  {"ig": 0,  "carbsPer100g": 1.0,  "proteinPer100g": 0.5,  "fatPer100g": 0.0},
    "bouillon de legume":   {"ig": 0,  "carbsPer100g": 1.0,  "proteinPer100g": 0.5,  "fatPer100g": 0.0},
    "bouillon de poulet":   {"ig": 0,  "carbsPer100g": 1.0,  "proteinPer100g": 2.0,  "fatPer100g": 0.5},
    "bouillon":             {"ig": 0,  "carbsPer100g": 1.0,  "proteinPer100g": 1.0,  "fatPer100g": 0.2},
    # ----- ALGUES / VEG -----
    "feuille de nori":      {"ig": 0,  "carbsPer100g": 40.0, "proteinPer100g": 41.0, "fatPer100g": 2.0},
    "wakame":               {"ig": 0,  "carbsPer100g": 9.0,  "proteinPer100g": 3.0,  "fatPer100g": 0.6},
    "algues nori":          {"ig": 0,  "carbsPer100g": 40.0, "proteinPer100g": 41.0, "fatPer100g": 2.0},
    "algues wakame sechees":{"ig": 0,  "carbsPer100g": 45.0, "proteinPer100g": 13.0, "fatPer100g": 2.5},
    "agar-agar":            {"ig": 0,  "carbsPer100g": 81.0, "proteinPer100g": 6.0,  "fatPer100g": 0.3},
    # ============================================================================
    # V2.99.24 — MINI_DB_EXTRA : ~80 entrées CIQUAL/USDA pour finir la queue longue
    # ============================================================================
    # ----- FROMAGES SUPPLÉMENTAIRES -----
    "halloumi":             {"ig": 27, "carbsPer100g": 2.3,  "proteinPer100g": 22.0, "fatPer100g": 22.0},
    "fromage frais type st-moret": {"ig": 27, "carbsPer100g": 4.0, "proteinPer100g": 8.0, "fatPer100g": 5.0},
    "buche de chevre":      {"ig": 27, "carbsPer100g": 2.5,  "proteinPer100g": 22.0, "fatPer100g": 24.0},
    "chevre fermier":       {"ig": 27, "carbsPer100g": 1.0,  "proteinPer100g": 18.0, "fatPer100g": 22.0},
    "gorgonzola":           {"ig": 27, "carbsPer100g": 0,    "proteinPer100g": 19.0, "fatPer100g": 29.0},
    "roquefort":            {"ig": 27, "carbsPer100g": 2.0,  "proteinPer100g": 19.0, "fatPer100g": 31.0},
    "pecorino":             {"ig": 27, "carbsPer100g": 0,    "proteinPer100g": 28.0, "fatPer100g": 33.0},
    "cottage cheese":       {"ig": 27, "carbsPer100g": 3.4,  "proteinPer100g": 11.0, "fatPer100g": 4.3},
    # ----- ÉPICES SUPPLÉMENTAIRES -----
    "sumac":                {"ig": 0,  "carbsPer100g": 70.0, "proteinPer100g": 3.0,  "fatPer100g": 12.0},
    "noix de muscade":      {"ig": 0,  "carbsPer100g": 49.0, "proteinPer100g": 6.0,  "fatPer100g": 36.0},
    "baton de cannelle":    {"ig": 0,  "carbsPer100g": 80.0, "proteinPer100g": 4.0,  "fatPer100g": 1.2},
    "baies de goji":        {"ig": 20, "carbsPer100g": 64.0, "proteinPer100g": 14.0, "fatPer100g": 0.4},
    "asafoetida":           {"ig": 0,  "carbsPer100g": 68.0, "proteinPer100g": 4.0,  "fatPer100g": 1.0},
    "citronnelle":          {"ig": 0,  "carbsPer100g": 25.0, "proteinPer100g": 1.8,  "fatPer100g": 0.5},
    "basilic thai":         {"ig": 0,  "carbsPer100g": 8.0,  "proteinPer100g": 3.2,  "fatPer100g": 0.6},
    "anis etoile":          {"ig": 0,  "carbsPer100g": 50.0, "proteinPer100g": 17.0, "fatPer100g": 16.0},
    "badiane":              {"ig": 0,  "carbsPer100g": 50.0, "proteinPer100g": 17.0, "fatPer100g": 16.0},
    "ail en poudre":        {"ig": 30, "carbsPer100g": 73.0, "proteinPer100g": 17.0, "fatPer100g": 0.7},
    "gingembre en poudre":  {"ig": 0,  "carbsPer100g": 71.0, "proteinPer100g": 9.0,  "fatPer100g": 4.0},
    "curcuma en poudre":    {"ig": 0,  "carbsPer100g": 67.0, "proteinPer100g": 8.0,  "fatPer100g": 10.0},
    "feuille de combava":   {"ig": 0,  "carbsPer100g": 11.0, "proteinPer100g": 1.5,  "fatPer100g": 0.3},
    # ----- LÉGUMES SUPPLÉMENTAIRES -----
    "pamplemousse":         {"ig": 25, "carbsPer100g": 8.0,  "proteinPer100g": 0.8,  "fatPer100g": 0.1},
    "mache":                {"ig": 15, "carbsPer100g": 3.6,  "proteinPer100g": 2.0,  "fatPer100g": 0.4},
    "potimarron":           {"ig": 75, "carbsPer100g": 5.0,  "proteinPer100g": 1.4,  "fatPer100g": 0.1},
    "pois gourmands":       {"ig": 35, "carbsPer100g": 7.0,  "proteinPer100g": 3.0,  "fatPer100g": 0.2},
    "cebette":              {"ig": 15, "carbsPer100g": 7.0,  "proteinPer100g": 1.8,  "fatPer100g": 0.2},
    "tomatille":            {"ig": 15, "carbsPer100g": 6.0,  "proteinPer100g": 1.0,  "fatPer100g": 1.0},
    "artichaut":            {"ig": 15, "carbsPer100g": 11.0, "proteinPer100g": 3.3,  "fatPer100g": 0.2},
    "chou rave":            {"ig": 15, "carbsPer100g": 6.2,  "proteinPer100g": 1.7,  "fatPer100g": 0.1},
    "citron confit":        {"ig": 20, "carbsPer100g": 12.0, "proteinPer100g": 1.0,  "fatPer100g": 0.5},
    "tomate coeur de boeuf":{"ig": 30, "carbsPer100g": 3.9,  "proteinPer100g": 0.9,  "fatPer100g": 0.2},
    "epinards en branche":  {"ig": 15, "carbsPer100g": 3.6,  "proteinPer100g": 2.9,  "fatPer100g": 0.4},
    "endives":              {"ig": 15, "carbsPer100g": 4.0,  "proteinPer100g": 0.9,  "fatPer100g": 0.1},
    "haricots beurre":      {"ig": 15, "carbsPer100g": 7.0,  "proteinPer100g": 1.8,  "fatPer100g": 0.2},
    "haricots plats":       {"ig": 15, "carbsPer100g": 7.0,  "proteinPer100g": 1.8,  "fatPer100g": 0.2},
    "petits oignons grelot":{"ig": 15, "carbsPer100g": 9.0,  "proteinPer100g": 1.1,  "fatPer100g": 0.1},
    "blettes":              {"ig": 15, "carbsPer100g": 4.0,  "proteinPer100g": 1.8,  "fatPer100g": 0.2},
    "cresson":              {"ig": 15, "carbsPer100g": 3.0,  "proteinPer100g": 2.2,  "fatPer100g": 0.1},
    "epis de mais":         {"ig": 65, "carbsPer100g": 19.0, "proteinPer100g": 3.3,  "fatPer100g": 1.4},
    # ----- VIANDES / POISSONS SUPPLÉMENTAIRES -----
    "agneau hache":         {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 20.0, "fatPer100g": 12.0},
    "pave de boeuf":        {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 26.0, "fatPer100g": 8.0},
    "filet de daurade":     {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 21.0, "fatPer100g": 2.0},
    "filet de truite":      {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 20.0, "fatPer100g": 8.0},
    "dos de cabillaud":     {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 18.0, "fatPer100g": 0.7},
    "filet mignon de porc": {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 22.0, "fatPer100g": 4.0},
    "lardons de volaille":  {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 23.0, "fatPer100g": 4.0},
    "blanc de dinde":       {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 24.0, "fatPer100g": 1.5},
    "escalope de poulet":   {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 23.0, "fatPer100g": 3.5},
    "cuisse de poulet":     {"ig": 0,  "carbsPer100g": 0,    "proteinPer100g": 19.0, "fatPer100g": 11.0},
    "crevettes decortiquees crues":{"ig":0,"carbsPer100g":0, "proteinPer100g": 18.0, "fatPer100g": 1.0},
    "noix de saint-jacques":{"ig": 0,  "carbsPer100g": 5.5,  "proteinPer100g": 17.0, "fatPer100g": 0.9},
    "encornets":            {"ig": 0,  "carbsPer100g": 1.4,  "proteinPer100g": 18.0, "fatPer100g": 1.4},
    "calamars":             {"ig": 0,  "carbsPer100g": 1.4,  "proteinPer100g": 18.0, "fatPer100g": 1.4},
    "moules":               {"ig": 0,  "carbsPer100g": 7.4,  "proteinPer100g": 12.0, "fatPer100g": 2.2},
    "tofu fume":            {"ig": 15, "carbsPer100g": 2.0,  "proteinPer100g": 17.0, "fatPer100g": 8.0},
    "seitan":               {"ig": 15, "carbsPer100g": 14.0, "proteinPer100g": 25.0, "fatPer100g": 2.0},
    # ----- CÉRÉALES / FÉCULENTS SUPPLÉMENTAIRES -----
    "chapati complet":      {"ig": 53, "carbsPer100g": 58.0, "proteinPer100g": 11.0, "fatPer100g": 3.0},
    "galette de mais":      {"ig": 65, "carbsPer100g": 82.0, "proteinPer100g": 7.0,  "fatPer100g": 1.0},
    "crackers sarrasin":    {"ig": 40, "carbsPer100g": 70.0, "proteinPer100g": 12.0, "fatPer100g": 4.0},
    "vermicelles de riz":   {"ig": 58, "carbsPer100g": 80.0, "proteinPer100g": 6.0,  "fatPer100g": 0.5},
    "fecule de mais":       {"ig": 85, "carbsPer100g": 92.0, "proteinPer100g": 0.3,  "fatPer100g": 0.0},
    "maizena":              {"ig": 85, "carbsPer100g": 92.0, "proteinPer100g": 0.3,  "fatPer100g": 0.0},
    "semoule de ble":       {"ig": 66, "carbsPer100g": 73.0, "proteinPer100g": 12.0, "fatPer100g": 1.0},
    "chapelure de pain complet":{"ig":70,"carbsPer100g": 68.0,"proteinPer100g": 12.0,"fatPer100g": 2.0},
    "galette de sarrasin":  {"ig": 40, "carbsPer100g": 60.0, "proteinPer100g": 9.0,  "fatPer100g": 1.5},
    "baguette complete":    {"ig": 53, "carbsPer100g": 55.0, "proteinPer100g": 11.0, "fatPer100g": 1.0},
    "muesli sans sucre":    {"ig": 45, "carbsPer100g": 65.0, "proteinPer100g": 11.0, "fatPer100g": 6.0},
    "biscotte complete":    {"ig": 65, "carbsPer100g": 70.0, "proteinPer100g": 12.0, "fatPer100g": 7.0},
    # ----- SAUCES / CONDIMENTS SUPPLÉMENTAIRES -----
    "vinaigre blanc":       {"ig": 0,  "carbsPer100g": 0.0,  "proteinPer100g": 0.0,  "fatPer100g": 0.0},
    "vinaigre de vin blanc":{"ig": 0,  "carbsPer100g": 0.0,  "proteinPer100g": 0.0,  "fatPer100g": 0.0},
    "vinaigre de xeres":    {"ig": 0,  "carbsPer100g": 0.0,  "proteinPer100g": 0.0,  "fatPer100g": 0.0},
    "huile de tournesol":   {"ig": 0,  "carbsPer100g": 0.0,  "proteinPer100g": 0.0,  "fatPer100g": 100.0},
    "huile de lin":         {"ig": 0,  "carbsPer100g": 0.0,  "proteinPer100g": 0.0,  "fatPer100g": 100.0},
    "huile d'avocat":       {"ig": 0,  "carbsPer100g": 0.0,  "proteinPer100g": 0.0,  "fatPer100g": 100.0},
    "pate de curry doux":   {"ig": 0,  "carbsPer100g": 24.0, "proteinPer100g": 4.0,  "fatPer100g": 10.0},
    "pate de curry vert":   {"ig": 0,  "carbsPer100g": 18.0, "proteinPer100g": 3.0,  "fatPer100g": 12.0},
    "pate de curry rouge":  {"ig": 0,  "carbsPer100g": 21.0, "proteinPer100g": 3.5,  "fatPer100g": 11.0},
    "tomates pelees":       {"ig": 30, "carbsPer100g": 4.0,  "proteinPer100g": 1.5,  "fatPer100g": 0.3},
    "tomates sechees":      {"ig": 35, "carbsPer100g": 55.0, "proteinPer100g": 14.0, "fatPer100g": 3.0},
    "olives vertes":        {"ig": 15, "carbsPer100g": 4.0,  "proteinPer100g": 1.0,  "fatPer100g": 11.0},
    # ----- LAITAGES SUPPLÉMENTAIRES -----
    "creme liquide legere": {"ig": 30, "carbsPer100g": 4.0,  "proteinPer100g": 3.0,  "fatPer100g": 15.0},
    "fromage rape":         {"ig": 27, "carbsPer100g": 1.0,  "proteinPer100g": 28.0, "fatPer100g": 28.0},
    "chocolat noir 70%":    {"ig": 30, "carbsPer100g": 46.0, "proteinPer100g": 8.0,  "fatPer100g": 42.0},
    "pepites de chocolat":  {"ig": 30, "carbsPer100g": 46.0, "proteinPer100g": 8.0,  "fatPer100g": 42.0},
    "cacao non sucre":      {"ig": 20, "carbsPer100g": 58.0, "proteinPer100g": 20.0, "fatPer100g": 14.0},
    "creme de coco":        {"ig": 35, "carbsPer100g": 6.0,  "proteinPer100g": 2.3,  "fatPer100g": 24.0},
    # ----- FRUITS SUPPLÉMENTAIRES -----
    "banane":               {"ig": 51, "carbsPer100g": 20.0, "proteinPer100g": 1.1,  "fatPer100g": 0.3},
    "melon charentais":     {"ig": 65, "carbsPer100g": 9.0,  "proteinPer100g": 0.8,  "fatPer100g": 0.2},
    "physalis":             {"ig": 35, "carbsPer100g": 11.0, "proteinPer100g": 1.9,  "fatPer100g": 0.7},
    "groseille":            {"ig": 25, "carbsPer100g": 10.0, "proteinPer100g": 1.4,  "fatPer100g": 0.5},
    "cassis":               {"ig": 25, "carbsPer100g": 11.0, "proteinPer100g": 1.4,  "fatPer100g": 0.4},
    "pomme golden":         {"ig": 38, "carbsPer100g": 14.0, "proteinPer100g": 0.3,  "fatPer100g": 0.2},
    "pomme reinette":       {"ig": 38, "carbsPer100g": 14.0, "proteinPer100g": 0.3,  "fatPer100g": 0.2},
    "noix de cajou non salee":{"ig":22, "carbsPer100g": 30.0, "proteinPer100g": 18.0, "fatPer100g": 44.0},
    # ----- LÉGUMINEUSES SUPPLÉMENTAIRES -----
    "pois casses":          {"ig": 25, "carbsPer100g": 22.0, "proteinPer100g": 8.3,  "fatPer100g": 0.4},
    "haricots mungo":       {"ig": 38, "carbsPer100g": 20.0, "proteinPer100g": 7.0,  "fatPer100g": 0.4},
    "haricots azuki":       {"ig": 35, "carbsPer100g": 25.0, "proteinPer100g": 8.0,  "fatPer100g": 0.5},
}

# ────────────────────────── HELPERS ──────────────────────────
def canonical(name):
    n = (name or "").strip().lower()
    n = n.replace('œ', 'oe').replace('æ', 'ae')
    n = ''.join(c for c in unicodedata.normalize('NFD', n) if unicodedata.category(c) != 'Mn')
    n = re.sub(r'\s*\([^)]*\)\s*', ' ', n)
    n = re.sub(r',.*$', '', n)
    n = re.sub(r'\ben poudre\b', ' ', n)
    n = re.sub(r'\bmoulu[es]?\b', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n

def fuzzy_match(query, candidates, threshold=0.7):
    """Retourne (best_match, score) ou (None, 0)."""
    matches = difflib.get_close_matches(query, candidates, n=1, cutoff=threshold)
    if not matches:
        return None, 0.0
    score = difflib.SequenceMatcher(None, query, matches[0]).ratio()
    return matches[0], score

# ────────────────────────── CORE ──────────────────────────
def collect_missing_from_lot(lot_file, varname, glyc_existing):
    """Charge le Lot, retourne dict {ingredient_canon: count}."""
    p = Path(lot_file).resolve()
    spec = importlib_util.spec_from_file_location("lot_module", p)
    mod = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, varname):
        candidates = [k for k in dir(mod) if k.startswith("LOT") and isinstance(getattr(mod, k), list)]
        if candidates:
            varname = candidates[0]
        else:
            print(f"{RED}❌ Variable LOT introuvable{RESET}")
            sys.exit(2)
    lot = getattr(mod, varname)

    missing = {}
    for r in lot:
        for ing_entry in r.get("ing", []):
            if not ing_entry: continue
            c = canonical(ing_entry[0])
            if c not in glyc_existing:
                missing[c] = missing.get(c, 0) + 1
    return missing

def load_existing_glycemic(repo_root):
    content = (Path(repo_root) / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="data-glycemic">\s*(\{.*?\})\s*</script>', content, re.DOTALL)
    data = json.loads(m.group(1))
    existing = {canonical(it["id"]): it for it in data["items"]}
    return content, data, existing

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?", help="Fichier Python avec LOTxx")
    parser.add_argument("--varname", default="LOT")
    parser.add_argument("--names", default=None, help="Liste manuelle (csv) au lieu d'un fichier")
    parser.add_argument("--apply", action="store_true", help="Applique les ajouts auto (haute confiance) directement à index.html")
    parser.add_argument("--threshold-auto", type=float, default=0.95)
    parser.add_argument("--threshold-manual", type=float, default=0.7)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    content, data, glyc_existing = load_existing_glycemic(repo_root)

    if args.names:
        missing = {canonical(n.strip()): 1 for n in args.names.split(",") if n.strip()}
    elif args.file:
        missing = collect_missing_from_lot(args.file, args.varname, glyc_existing)
    else:
        print(f"{RED}❌ Fournir un fichier (positionnel) ou --names \"liste,csv\"{RESET}")
        sys.exit(2)

    print(f"{BOLD}🔍 auto-enrich-glycemic.py{RESET}")
    print(f"  ingrédients manquants : {len(missing)}")
    print(f"  base existante : {len(glyc_existing)} entrées + mini-DB : {len(MINI_DB)} candidates")
    print()

    auto_add = []     # ingrédients à ajouter automatiquement (confiance >= 95%)
    manual_check = [] # à valider (70-94%)
    to_complete = []  # pas de match (< 70%)

    db_keys = list(MINI_DB.keys())
    for name in sorted(missing.keys(), key=lambda x: -missing[x]):
        # Tentative 1 : direct dans la mini-DB
        if name in MINI_DB:
            entry = {"id": name, **MINI_DB[name]}
            auto_add.append((name, entry, 1.0, "direct"))
            continue
        # Tentative 2 : fuzzy match
        match, score = fuzzy_match(name, db_keys, threshold=args.threshold_manual)
        if match and score >= args.threshold_auto:
            entry = {"id": name, **MINI_DB[match]}
            auto_add.append((name, entry, score, match))
        elif match:
            manual_check.append((name, match, score))
        else:
            to_complete.append(name)

    # ──── Affichage rapport ────
    if auto_add:
        print(f"{GREEN}{BOLD}✅ AUTO-AJOUT ({len(auto_add)}) — confiance ≥{args.threshold_auto:.0%}{RESET}")
        for name, entry, score, src in auto_add[:20]:
            tag = f"{score:.0%} {src}" if src != "direct" else "direct"
            print(f"  {GREEN}+{RESET} {name:35} ig={entry['ig']:3}  P={entry['proteinPer100g']:5}  C={entry['carbsPer100g']:5}  F={entry['fatPer100g']:5}  {DIM}({tag}){RESET}")
        if len(auto_add) > 20:
            print(f"  {DIM}... et {len(auto_add) - 20} autres{RESET}")
        print()

    if manual_check:
        print(f"{YELLOW}{BOLD}⚠️  VALIDATION MANUELLE ({len(manual_check)}) — confiance {args.threshold_manual:.0%}-{args.threshold_auto:.0%}{RESET}")
        for name, match, score in manual_check[:20]:
            print(f"  {YELLOW}?{RESET} {name:35} → match probable: {match!r} ({score:.0%})")
        if len(manual_check) > 20:
            print(f"  {DIM}... et {len(manual_check) - 20} autres{RESET}")
        print()

    if to_complete:
        print(f"{RED}{BOLD}❌ À COMPLÉTER MANUELLEMENT ({len(to_complete)}) — pas de match en mini-DB{RESET}")
        for name in to_complete[:15]:
            print(f"  {RED}–{RESET} {name}")
        if len(to_complete) > 15:
            print(f"  {DIM}... et {len(to_complete) - 15} autres{RESET}")
        print()

    # ──── Application des auto-ajouts ────
    if args.apply and auto_add:
        existing_ids = {it["id"] for it in data["items"]}
        added = 0
        for name, entry, _, _ in auto_add:
            if entry["id"] not in existing_ids:
                data["items"].append(entry)
                added += 1
        new_raw = json.dumps(data, ensure_ascii=False, indent=2)
        m = re.search(r'(<script type="application/json" id="data-glycemic">\s*)(\{.*?\})(\s*</script>)', content, re.DOTALL)
        new_content = content[:m.start()] + m.group(1) + new_raw + m.group(3) + content[m.end():]
        (repo_root / "index.html").write_text(new_content, encoding="utf-8")
        print(f"{GREEN}{BOLD}✅ {added} entrées ajoutées à index.html{RESET}")
        print(f"   total data-glycemic : {len(data['items'])}")
    elif auto_add and not args.apply:
        print(f"{DIM}→ Pour appliquer : python3 scripts/auto-enrich-glycemic.py <file> --apply{RESET}")

    sys.exit(0 if not to_complete else 1)


if __name__ == "__main__":
    main()
