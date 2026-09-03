# -*- coding: utf-8 -*-
"""Le dessin du plan de débit.

Une seule scène porte TOUTES les planches, empilées, chacune sous son
cartouche. C'est ce qui change le plus par rapport à la première
interface : une planche seule affichée dans un panneau haut ne remplit
rien — un brin de 4 m sur 200 mm ajusté en largeur ne fait qu'un filet
de quarante pixels au milieu du vide. Empilées, les planches occupent
la hauteur, et surtout on lit le débit ENTIER d'un coup d'œil, ce qu'on
ne pouvait pas faire en cliquant les planches une par une.

Le plan garde des couleurs claires même sur thème sombre : c'est une
feuille qu'on imprime et qu'on emporte à l'établi.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsPolygonItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView,
)

import apparence
import optimiseur as opt


def _centre_de_gravite(points):
    aire, cx, cy = 0.0, 0.0, 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        d = x1 * y2 - x2 * y1
        aire += d
        cx += (x1 + x2) * d
        cy += (y1 + y2) * d
    if abs(aire) < 1e-9:
        return points[0]
    return cx / (3 * aire), cy / (3 * aire)


class VuePlan(QGraphicsView):
    """Planches débitées : pièces en couleur, chutes hachurées, et le
    reste — sciure et rebuts trop petits — en fond de papier."""

    ZOOM_MIN, ZOOM_MAX = 0.02, 40.0

    # Plafond d'une image rendue, en pixels (≈ 80 Mo en ARGB32).
    PIXELS_MAX = 20_000_000

    # Hauteur visée, en pixels, pour le titre d'une planche une fois le
    # plan ajusté à la fenêtre.
    _CARTOUCHE_PX = 14.0

    # Largeur de rendu pour laquelle les tailles de texte ci-dessus sont
    # réglées. Au-delà, il faut les grossir d'autant : elles sont fixées
    # en PIXELS, ce qui ne veut plus rien dire sur une page à 1200 points
    # par pouce — un plan imprimé sortait avec des noms de 0,4 mm.
    LARGEUR_LISIBLE = 1600.0

    def __init__(self):
        super().__init__()
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QBrush(apparence.fond_etabli(self)))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # Centré : une planche de 12:1 ne remplira jamais un panneau
        # de 3:2, autant que le vide se répartisse plutôt que de
        # s'amasser sous le dessin comme un oubli.
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._debits = []          # [(numero, Debit)] tels qu'affichés
        self._etiquettes = []
        self._cadres = {}          # numero -> QGraphicsRectItem du contour
        self._zones = {}           # numero -> QRectF de la planche en scène
        self._poses = {}           # QGraphicsRectItem -> (numero, Pose)
        self._selection = None
        self.epinglees = set()     # numéros des planches épinglées
        self.au_menu = None        # rappel (numero, pose|None, position)
        self.message_vide = ""     # ce qu'on écrit quand il n'y a rien
        self._zoom_manuel = False
        self._traits_visibles = False
        self._facteur_texte = 1.0
        self.couleurs = {}          # référence -> QColor, posée par la fenêtre

    # -- construction de la scène ---------------------------------------

    def debits_affiches(self) -> list:
        return list(self._debits)

    def afficher(self, debits: list, traits: bool = None,
                 largeur_prevue: int = None, facteur_texte: float = 1.0):
        """``debits`` : liste de couples (numéro affiché, Debit).

        ``largeur_prevue`` : largeur en pixels à laquelle le plan sera vu,
        si ce n'est pas celle de cette vue — c'est le cas d'une vue
        montée hors écran pour composer une page imprimée, dont la taille
        du widget ne veut rien dire.

        ``facteur_texte`` : multiplie toutes les tailles de texte. Elles
        sont réglées pour un rendu d'environ :data:`LARGEUR_LISIBLE`
        pixels ; un rendu quatre fois plus large veut des lettres quatre
        fois plus grandes, sans quoi elles fondent en taches grises."""
        if traits is not None:
            self._traits_visibles = traits
        self._facteur_texte = max(0.1, facteur_texte)
        self._debits = list(debits)
        self._zoom_manuel = False
        self.setBackgroundBrush(QBrush(apparence.fond_etabli(self)))
        scene = self.scene()
        scene.clear()
        self._etiquettes = []
        self._cadres = {}
        self._zones = {}
        self._poses = {}
        self._selection = None
        if not self._debits:
            scene.setSceneRect(QRectF())
            return

        longueur_max = max(d.planche.longueur for _, d in self._debits)
        largeur_max = max(d.planche.largeur for _, d in self._debits)
        # Le cartouche est dessiné en millimètres de scène (il grandit
        # donc au zoom), mais sa taille est choisie pour faire une hauteur
        # de PIXELS donnée une fois le plan ajusté — c'est là qu'on le
        # lit. Le déduire de la largeur des planches ne marchait pas :
        # cinq brins de 4 m sur 150 se voient à 0,22 px/mm, et le titre
        # tombait à huit pixels, illisible.
        echelle_prevue = (largeur_prevue or max(self.viewport().width(), 400)) \
            / longueur_max

        def tailles(echelle):
            # Pas de plancher proportionnel à la largeur : sur un panneau
            # de 600 × 400 il faisait un titre de 48 mm, plus haut qu'une
            # pièce.
            h = min(self._CARTOUCHE_PX * self._facteur_texte / echelle,
                    largeur_max * 0.55)
            # Le titre se pose EN HAUT de sa bande : le reste de la bande
            # reçoit les étiquettes qui débordent par le haut de la planche
            # (celles des pièces au ras du bord), qui sinon s'écrivent par
            # dessus le titre.
            return h, h * 2.2, h * 1.4

        hauteur_texte, bande, interligne = tailles(echelle_prevue)
        if largeur_prevue is None:
            # Deux panneaux de 600 × 400 empilés : la vue est bridée par la
            # HAUTEUR, pas la largeur, et l'échelle réelle est bien plus
            # petite que prévu — le titre sortait à quatre pixels. Une
            # seconde passe à l'échelle de la hauteur.
            hauteur_scene = sum(d.planche.largeur + bande + interligne
                                for _, d in self._debits)
            echelle_h = max(self.viewport().height(), 300) / max(hauteur_scene, 1)
            if echelle_h < echelle_prevue:
                hauteur_texte, bande, interligne = tailles(echelle_h)

        y = 0.0
        for numero, debit in self._debits:
            self._cartouche(scene, numero, debit, y, hauteur_texte)
            y += bande
            self._planche(scene, numero, debit, y)
            y += debit.planche.largeur + interligne

        scene.setSceneRect(QRectF(0, 0, longueur_max, max(y - interligne, 1)))
        self._ajuster()

    def _cartouche(self, scene, numero, debit, y, hauteur_texte):
        pl = debit.planche
        marque = "chute" if pl.chute else ("catalogue" if pl.illimite else "")
        plusieurs = pl.quantite > 1 or pl.illimite
        exemplaire = " (ex. %d)" % debit.exemplaire if plusieurs else ""
        libelle = ("%d.  %s%s   —   %s × %s × %s mm, %s%s   —   %d pièce(s),"
                   " rendement %s %%%s"
                   % (numero, pl.reference, exemplaire, opt._mm(pl.longueur),
                      opt._mm(pl.largeur), opt._mm(pl.epaisseur), pl.matiere,
                      " [%s]" % marque if marque else "",
                      len(debit.poses), opt._pct(debit.rendement),
                      "   —   ÉPINGLÉE" if numero in self.epinglees else ""))
        texte = QGraphicsSimpleTextItem(libelle)
        police = QFont()
        police.setPointSize(10)
        police.setBold(True)
        texte.setFont(police)
        texte.setBrush(QBrush(apparence.encre_marge(self)))
        boite = texte.boundingRect()
        if boite.height() > 0:
            texte.setScale(hauteur_texte / boite.height())
        texte.setPos(0, y + hauteur_texte * 0.05)
        scene.addItem(texte)

    def _planche(self, scene, numero, debit, y_haut):
        pl = debit.planche
        zone = QRectF(0, y_haut, pl.longueur, pl.largeur)
        self._zones[numero] = zone

        fond = QGraphicsRectItem(zone)
        fond.setBrush(QBrush(apparence.PLAN_PAPIER))
        fond.setPen(QPen(apparence.PLAN_BORD, max(pl.longueur, 1) / 500))
        fond.setToolTip("Ce que ni pièce ni chute ne couvre est la perte :"
                        " sciure et rebuts sous les minis de chute.")
        scene.addItem(fond)

        # Les défauts déclarés — recoupes de bouts et de rives, zones
        # écartées — se voient AVANT les pièces : un trou dans le plan
        # sans explication ferait chercher une erreur de l'optimiseur.
        for x, y, dx, dy, info in self._zones_ecartees(pl):
            self._rectangle(scene, numero, x, y, dx, dy, pl.largeur, y_haut,
                            apparence.PLAN_DEFAUT, None, None, hachure=True,
                            trait=apparence.PLAN_DEFAUT_TRAIT, info=info)

        for pose in debit.poses:
            rect = self._rectangle(
                scene, numero, pose.x, pose.y, pose.dim_x, pose.dim_y,
                pl.largeur, y_haut, self.couleur(pose.piece.reference),
                "%s\n%s × %s" % (pose.piece.reference, opt._mm(pose.dim_x),
                                 opt._mm(pose.dim_y)),
                pose.piece.reference, contour=pose.contour)
            self._poses[rect] = (numero, pose)

        for chute in debit.chutes:
            self._rectangle(
                scene, numero, chute.x, chute.y, chute.dim_x, chute.dim_y,
                pl.largeur, y_haut, apparence.PLAN_CHUTE,
                "chute\n%s × %s" % (opt._mm(chute.dim_x), opt._mm(chute.dim_y)),
                "chute", hachure=True)

        if self._traits_visibles:
            self._traits_de_scie(scene, debit, y_haut)

        cadre = QGraphicsRectItem(zone)
        cadre.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        cadre.setPen(QPen(Qt.PenStyle.NoPen))
        cadre.setZValue(10)
        scene.addItem(cadre)
        self._cadres[numero] = cadre
        if numero in self.epinglees:
            # Un liseré pointillé sur toute la planche : elle ne bougera
            # plus au prochain calcul, il faut que ça se voie.
            epingle = QGraphicsRectItem(zone)
            stylo = QPen(apparence.PLAN_BORD, max(pl.longueur, 1) / 300)
            stylo.setStyle(Qt.PenStyle.DashLine)
            epingle.setPen(stylo)
            epingle.setZValue(9)
            epingle.setToolTip("Planche épinglée : reprise telle quelle au"
                               " prochain calcul (clic droit pour relâcher).")
            scene.addItem(epingle)

    def couleur(self, reference: str):
        return self.couleurs.get(reference) or apparence.couleur_piece(reference)

    @staticmethod
    def _zones_ecartees(pl) -> list:
        """Les rectangles perdus d'avance : (x, y, dx, dy, info-bulle)."""
        zones = []
        if pl.recoupe_bouts > 0:
            info = "Recoupe de bout : %s mm" % opt._mm(pl.recoupe_bouts)
            zones.append((0.0, 0.0, pl.recoupe_bouts, pl.largeur, info))
            zones.append((pl.longueur - pl.recoupe_bouts, 0.0,
                          pl.recoupe_bouts, pl.largeur, info))
        if pl.recoupe_rives > 0:
            info = "Recoupe de rive : %s mm" % opt._mm(pl.recoupe_rives)
            zones.append((0.0, 0.0, pl.longueur, pl.recoupe_rives, info))
            zones.append((0.0, pl.largeur - pl.recoupe_rives, pl.longueur,
                          pl.recoupe_rives, info))
        for x, y, dx, dy in pl.defauts:
            zones.append((x, y, dx, dy,
                          "Défaut écarté : %s × %s en (%s, %s)"
                          % (opt._mm(dx), opt._mm(dy), opt._mm(x), opt._mm(y))))
        return zones

    def _traits_de_scie(self, scene, debit, y_haut):
        """Les coupes dans leur ordre d'exécution — chaque trait traverse
        de bord à bord le morceau courant, tel qu'on le passera à la scie.
        Chaque trait porte son numéro à son départ : leur rang n'était
        lisible qu'en info-bulle, donc pas sur le papier."""
        pl = debit.planche
        epaisseur = max(pl.longueur, pl.largeur) / 700
        for coupe in debit.coupes:
            if coupe.sens == opt.DELIGNAGE:
                y = y_haut + pl.largeur - coupe.position
                ligne = scene.addLine(coupe.de, y, coupe.a, y)
                depart = (coupe.de, y)
            else:
                haut = y_haut + pl.largeur - coupe.a
                ligne = scene.addLine(coupe.position, y_haut + pl.largeur - coupe.de,
                                      coupe.position, haut)
                depart = (coupe.position, haut)
            stylo = QPen(apparence.PLAN_TRAIT_SCIE, epaisseur)
            stylo.setStyle(Qt.PenStyle.DashLine)
            ligne.setPen(stylo)
            ligne.setZValue(5)
            ligne.setToolTip("Coupe n° %d — %s" % (coupe.ordre, coupe.sens))
            self._numero_de_coupe(scene, coupe, depart)

    def _numero_de_coupe(self, scene, coupe, depart):
        numero = QGraphicsSimpleTextItem(str(coupe.ordre))
        numero.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        police = QFont()
        police.setPointSizeF(6.5 * self._facteur_texte)
        police.setBold(True)
        numero.setFont(police)
        numero.setBrush(QBrush(apparence.PLAN_TRAIT_SCIE))
        numero.setZValue(7)
        numero.setToolTip("Coupe n° %d — %s" % (coupe.ordre, coupe.sens))
        boite = numero.boundingRect()
        numero.setPos(*depart)
        ecart = 1.5 * self._facteur_texte
        # Un délignage part du bord gauche du morceau : le numéro se pose
        # juste au-dessus du trait. Un tronçonnage part du haut : juste à
        # droite du trait, au ras du haut.
        if coupe.sens == opt.DELIGNAGE:
            decalage = (ecart, -boite.height())
        else:
            decalage = (ecart, ecart)
        numero.setTransform(numero.transform().translate(*decalage))
        scene.addItem(numero)

    def drawForeground(self, peintre, rect):
        super().drawForeground(peintre, rect)
        if self._debits or not self.message_vide:
            return
        # Un rectangle gris muet fait chercher une panne ; un plan vide
        # dit quoi faire. Dessiné en coordonnées de la fenêtre, pas de
        # la scène, pour ignorer le zoom.
        peintre.save()
        peintre.resetTransform()
        police = QFont()
        police.setPointSizeF(11)
        peintre.setFont(police)
        peintre.setPen(QPen(apparence.encre_marge(self)))
        peintre.drawText(self.viewport().rect(),
                         int(Qt.AlignmentFlag.AlignCenter), self.message_vide)
        peintre.restore()

    def _rectangle(self, scene, numero, x, y, dx, dy, largeur_planche,
                   y_haut, couleur, etiquette, etiquette_courte,
                   hachure=False, trait=None, info=None, contour=()):
        """``etiquette`` à ``None`` : un rectangle muet (défaut, recoupe),
        qui ne porte que son info-bulle ``info``. ``contour`` : une pose
        imbriquée se dessine par son polygone, l'étiquette se règle sur
        sa boîte."""
        # Les données ont leur origine en bas-gauche ; QGraphicsRectItem
        # place la sienne en haut-gauche — on retourne y ici, une fois,
        # plutôt que de retourner toute la vue (le texte resterait lisible).
        y_qt = y_haut + largeur_planche - y - dy
        if contour:
            rect = QGraphicsPolygonItem(QPolygonF(
                [QPointF(px, y_haut + largeur_planche - py)
                 for px, py in contour]))
        else:
            rect = QGraphicsRectItem(x, y_qt, dx, dy)
        if hachure:
            # Chute : hachure simple. Défaut écarté : croisillon — de loin,
            # deux hachures de même sens se confondaient.
            motif = (Qt.BrushStyle.DiagCrossPattern if trait
                     else Qt.BrushStyle.BDiagPattern)
            rect.setBrush(QBrush(couleur, motif))
            rect.setPen(QPen(trait or apparence.PLAN_CHUTE_TRAIT, 1))
        else:
            rect.setBrush(QBrush(couleur))
            rect.setPen(QPen(apparence.PLAN_BORD, 1))
        rect.setToolTip(info if etiquette is None
                        else etiquette.replace("\n", " "))
        scene.addItem(rect)
        if etiquette is None:
            return rect

        # Une planche de menuiserie est souvent longue et étroite (un
        # 150×3000) : la pièce posée peut être trop basse pour ses deux
        # lignes complètes tout en étant bien assez large pour son seul
        # nom — ou pour les deux SUR UNE LIGNE, ce qui manquait : un
        # montant de 1750 × 60 faisait 800 px de large et n'affichait que
        # « montant ». Les variantes sont préparées ; _visibilite choisit
        # celle qui loge sous le zoom courant, ou aucune (l'info-bulle
        # reste), et règle la taille du texte sur la hauteur de la pièce.
        if contour:
            # Une forme imbriquée : son nom seul, au centre de gravité du
            # polygone (le centre de la boîte tombe dans l'échancrure d'une
            # équerre, et deux équerres emboîtées y écrivaient l'une sur
            # l'autre). Le budget de place est réduit : la boîte est plus
            # large que la forme.
            cx, cy = _centre_de_gravite(contour)
            dedans = [self._texte_centre(scene, etiquette_courte, cx - dx * 0.3,
                                         y_haut + largeur_planche - cy - dy * 0.3,
                                         dx * 0.6, dy * 0.6)]
            dx, dy = dx * 0.6, dy * 0.6
        else:
            dedans = [self._texte_centre(scene, chaine, x, y_qt, dx, dy)
                      for chaine in (etiquette,
                                     etiquette.replace("\n", "  ·  "),
                                     etiquette_courte)]
        hors, cote_hors = None, None
        if y < 0.5:
            # Pièce au ras du bord bas : rien n'occupe l'en-dessous, et
            # l'interligne entre planches y laisse la place — l'étiquette
            # peut déborder là sans chevaucher un voisin.
            hors = self._texte_centre(scene, etiquette_courte, x, y_qt + dy,
                                      dx, 0, cote="dessous")
            cote_hors = "dessous"
        elif y + dy > largeur_planche - 0.5:
            hors = self._texte_centre(scene, etiquette_courte, x, y_qt, dx, 0,
                                      cote="dessus")
            cote_hors = "dessus"
        self._etiquettes.append(
            (dedans, hors, cote_hors, dx, dy, x + dx / 2, numero))
        return rect

    TAILLE_MINI, TAILLE_MAXI, TAILLE_HORS = 6.5, 11.0, 6.0

    def _texte_centre(self, scene, chaine, x, y_qt, dx, dy, cote="dedans"):
        texte = QGraphicsSimpleTextItem(chaine)
        texte.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        texte.setBrush(QBrush(apparence.PLAN_BORD if cote == "dedans"
                              else apparence.encre_marge(self)))
        texte.setZValue(6)
        # ItemIgnoresTransformations ancre pos() au point de la scène (donc
        # zoomé avec la vue) mais dessine ensuite en pixels non zoomés — le
        # centrage se fait par une transformation propre à l'item, en
        # pixels, refait à chaque changement de taille (_tailler).
        texte.setPos(x + dx / 2, y_qt + dy / 2)
        self._tailler(texte, self.TAILLE_HORS if cote != "dedans"
                      else self.TAILLE_MINI, cote)
        scene.addItem(texte)
        return texte, cote

    def _tailler(self, texte, taille, cote):
        """Règle la police et recentre ; rend la boîte en pixels."""
        police = QFont()
        police.setPointSizeF(taille * self._facteur_texte)
        texte.setFont(police)
        boite = texte.boundingRect()
        ecart = 3 * self._facteur_texte
        if cote == "dessus":
            decalage_y = -boite.height() - ecart
        elif cote == "dessous":
            decalage_y = ecart
        else:
            decalage_y = -boite.height() / 2
        transformation = texte.transform()
        transformation.reset()
        texte.setTransform(transformation.translate(-boite.width() / 2,
                                                    decalage_y))
        return boite

    # -- sélection --------------------------------------------------------

    def selectionner(self, numero, defiler=True):
        """Encadre une planche et l'amène sous les yeux — la liste et le
        dessin désignent ainsi toujours la même planche."""
        for num, cadre in self._cadres.items():
            if num == numero:
                # Fin : un cadre épais couvrait le liseré pointillé d'une
                # planche épinglée.
                stylo = QPen(apparence.ORANGE,
                             max(self.scene().sceneRect().width(), 1) / 600)
                cadre.setPen(stylo)
            else:
                cadre.setPen(QPen(Qt.PenStyle.NoPen))
        self._selection = numero
        if defiler and numero in self._zones:
            self.ensureVisible(self._zones[numero], 20, 20)

    def planche_sous(self, position):
        """Le numéro de la planche sous un point de la vue, ou None."""
        point = self.mapToScene(position)
        for numero, zone in self._zones.items():
            if zone.contains(point):
                return numero
        return None

    def pose_sous(self, position):
        """(numéro, Pose) de la pièce sous un point de la vue, ou None."""
        for item in self.items(position):
            if item in self._poses:
                return self._poses[item]
        return None

    def mousePressEvent(self, evenement):
        numero = self.planche_sous(evenement.position().toPoint())
        if numero is not None and numero != self._selection:
            self.selectionner(numero, defiler=False)
            if callable(getattr(self, "au_clic_planche", None)):
                self.au_clic_planche(numero)
        super().mousePressEvent(evenement)

    def contextMenuEvent(self, evenement):
        """Clic droit : la fenêtre bâtit le menu (épingler la planche,
        imposer une planche à la pièce) — la vue ne sait que ce qu'il y
        a sous la souris."""
        position = evenement.pos()
        numero = self.planche_sous(position)
        if numero is None or not callable(self.au_menu):
            super().contextMenuEvent(evenement)
            return
        trouvee = self.pose_sous(position)
        pose = trouvee[1] if trouvee else None
        self.au_menu(numero, pose, evenement.globalPos())

    # -- zoom -------------------------------------------------------------

    def wheelEvent(self, evenement):
        # Molette = défilement (la pile de planches est plus haute que la
        # vue), Ctrl+molette = zoom, comme dans toute visionneuse. La
        # molette seule zoomait dans la première version, où il n'y avait
        # jamais rien à faire défiler.
        if not (evenement.modifiers() & Qt.KeyboardModifier.ControlModifier):
            super().wheelEvent(evenement)
            return
        self.zoomer(1.25 if evenement.angleDelta().y() > 0 else 1 / 1.25)

    def zoomer(self, facteur):
        if not self._debits:
            return
        echelle = self.transform().m11() * facteur
        # Une planche très longue s'ajuste déjà loin sous ZOOM_MIN :
        # rejeter tout zoom qui reste sous le plancher bloquerait le zoom
        # AVANT pour toujours. Seul le sens qui s'approche de la borne
        # doit s'y heurter.
        if facteur > 1 and echelle > self.ZOOM_MAX:
            return
        if facteur < 1 and echelle < self.ZOOM_MIN:
            return
        self._zoom_manuel = True
        self.scale(facteur, facteur)
        self._visibilite(self.transform().m11())

    def mouseDoubleClickEvent(self, evenement):
        self.ajuster()
        super().mouseDoubleClickEvent(evenement)

    def ajuster(self):
        self._zoom_manuel = False
        self._ajuster()

    def resizeEvent(self, evenement):
        super().resizeEvent(evenement)
        self._ajuster()

    def _ajuster(self):
        if self.scene() is None or self.scene().sceneRect().isEmpty():
            return
        if not self._zoom_manuel:
            self.fitInView(self.scene().sceneRect(),
                           Qt.AspectRatioMode.KeepAspectRatio)
        self._visibilite(self.transform().m11())

    def _visibilite(self, echelle):
        # Une étiquette « hors » (au-dessus/en-dessous, débordant dans la
        # marge) ne vérifie d'abord que SA propre pièce — deux petites
        # pièces voisines peuvent chacune y passer et quand même se
        # chevaucher, illisibles côte à côte. Les candidates qui passent
        # ce premier tri s'accumulent par planche ET par côté, pour un
        # second tri qui les compare entre elles. Par planche : deux
        # planches empilées ont chacune leur propre bande de marge.
        candidats = {}
        marge = 4 * self._facteur_texte
        for dedans, hors, cote_hors, dx, dy, x_centre, numero in \
                self._etiquettes:
            # La taille suit la hauteur de la pièce à l'écran, entre deux
            # bornes : une tablette de 180 mm n'a pas à s'écrire aussi
            # petit qu'un tasseau de 20.
            taille = min(self.TAILLE_MAXI,
                         max(self.TAILLE_MINI, dy * echelle * 0.2))
            retenue = None
            for rang, (texte, cote) in enumerate(dedans):
                boite = self._tailler(texte, taille if rang < 2
                                      else max(self.TAILLE_MINI, taille - 1),
                                      cote)
                if (retenue is None and dx * echelle >= boite.width() + marge
                        and dy * echelle >= boite.height() + marge):
                    retenue = texte
                texte.setVisible(False)
            if retenue is not None:
                retenue.setVisible(True)
                if hors:
                    hors[0].setVisible(False)
            elif hors:
                texte_h, cote = hors
                boite_h = self._tailler(texte_h, self.TAILLE_HORS, cote)
                if dx * echelle >= boite_h.width() + marge:
                    candidats.setdefault((numero, cote_hors), []).append(
                        (x_centre * echelle, boite_h.width(), texte_h))
                else:
                    texte_h.setVisible(False)

        for groupe in candidats.values():
            groupe.sort(key=lambda c: c[0])
            bord_precedent = None
            for centre_px, largeur_px, texte_h in groupe:
                gauche = centre_px - largeur_px / 2
                if bord_precedent is not None and \
                        gauche < bord_precedent + 4 * self._facteur_texte:
                    texte_h.setVisible(False)
                else:
                    texte_h.setVisible(True)
                    bord_precedent = centre_px + largeur_px / 2

    # -- export -----------------------------------------------------------

    def rendre_image(self, largeur_px: int = 2400):
        """L'image du plan AFFICHÉ, à résolution choisie — indépendante
        de la taille de la fenêtre : un plan imprimé n'a pas les mêmes
        contraintes de place qu'un widget à l'écran, les étiquettes s'y
        recalculent donc à l'échelle du rendu, pas celle affichée.

        La largeur demandée est réduite si l'image dépassait
        :data:`PIXELS_MAX`. Un plan de soixante planches fait une scène
        de 7:1 : à 2400 px de large il réclamait 16 774 px de haut, soit
        161 Mo en mémoire — et un PNG de cette forme ne s'imprime pas.

        Rend ``None`` s'il n'y a rien à dessiner ou si l'image n'a pas pu
        être allouée.
        """
        if not self._debits:
            return None
        scene = self.scene()
        rect = scene.sceneRect()
        proportion = rect.height() / rect.width()
        largeur_px = max(1, int(largeur_px))
        if largeur_px * largeur_px * proportion > self.PIXELS_MAX:
            largeur_px = max(1, int((self.PIXELS_MAX / proportion) ** 0.5))
        hauteur_px = max(1, round(largeur_px * proportion))

        # Le cadre orange marque la planche choisie À L'ÉCRAN ; sur le
        # papier il n'a aucun sens et fausserait la lecture.
        cadres = {n: c.pen() for n, c in self._cadres.items()}
        for cadre in self._cadres.values():
            cadre.setPen(QPen(Qt.PenStyle.NoPen))
        self._visibilite(largeur_px / rect.width())
        image = QImage(largeur_px, hauteur_px, QImage.Format.Format_ARGB32)
        if image.isNull():
            for numero, stylo in cadres.items():
                self._cadres[numero].setPen(stylo)
            self._visibilite(self.transform().m11())
            return None
        image.fill(Qt.GlobalColor.white)
        peintre = QPainter(image)
        peintre.setRenderHint(QPainter.RenderHint.Antialiasing)
        scene.render(peintre)
        peintre.end()
        for numero, stylo in cadres.items():
            self._cadres[numero].setPen(stylo)
        self._visibilite(self.transform().m11())
        return image

    def exporter_image(self, chemin: str, largeur_px: int = 2400):
        """Enregistre le plan affiché tel quel. Rend le couple (largeur,
        hauteur) réellement écrit, ou ``None`` en cas d'échec.

        L'interface passe plutôt par une vue jetable (voir
        ``FenetrePrincipale._image_du_plan``) : le texte doit y être
        grossi à la mesure de la résolution demandée, ce qui suppose de
        reconstruire la scène — on ne va pas défigurer celle qu'on
        regarde pour écrire un fichier."""
        image = self.rendre_image(largeur_px)
        if image is None or not image.save(chemin):
            return None
        return image.width(), image.height()
