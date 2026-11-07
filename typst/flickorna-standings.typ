
    
#import "lib.typ": stylish_table
#set document(title: [Flickornas Ställning],
author: "Stockholms Schackförbunds UngdomsUtskott"
)
#set text(8pt, font: "Roboto")
#set page(numbering: "1 / 1",
margin: ( top: 2.8cm, rest: 0.8cm),
header: align(right+horizon)[ #link("https://www.stockholmsschack.se/juniortavlingar/")[#image("stsf.png", height: 50%)] ]
,header-ascent: -15pt
)
#context [
  #set text(12pt, font: "Roboto", weight: "bold", fill: rgb("#0072B2"))
  Flickornas Ställning
]
(Utskrift gäller: #datetime.today().display())
#stylish_table()[
      #table(
            
columns: (auto, auto, 1fr, auto, auto, auto, auto, auto, auto, auto, auto, auto),
align: (right + horizon, left + horizon, left + horizon, left + horizon, right + horizon, right + horizon, right + horizon, right + horizon, right + horizon, right + horizon, right + horizon, right + horizon),
rows: 1.8em,
table.header([*\#*], [*Namn*], [*Född*], [*Klubb*], [*1*], [*2*], [*3*], [*4*], [*5*], [*6*], [*7*], [*Σ*]),
  [1], [Fiona Tsai], [2013], [SK Rockaden Sthlm], [14], [19], [21], [25], [14], [], [18], [111],
  [2], [#highlight[Rafaela Davelius]], [2014], [SK Rockaden Sthlm], [22], [11], [17], [14], [11], [9], [25], [109],
  [3], [Idun Horn], [2016], [Trojanska Hästen], [9], [25], [25], [], [], [25], [25], [109],
  [4], [Shanvika Bendi], [2014], [Kristallens SK], [], [23], [22], [], [25], [19], [], [89],
  [5], [#highlight[Nina Bartoszuk Knezevic]], [2016], [Trojanska Hästen], [7], [11], [18], [10], [25], [11], [7], [89],
  [6], [Rita Sehlberg Gorgis], [2015], [SK Rockaden Sthlm], [10], [21], [12], [22], [8], [], [14], [87],
  [7], [Miya Sundell], [2017], [Wasa SK], [6], [], [], [25], [13], [18], [25], [87],
  [8], [Nithika Kesavan], [2015], [Wasa SK], [16], [12], [18], [], [18], [16], [], [80],
  [9], [Sigrid Gisslén], [2016], [Kosmos SK], [], [], [22], [22], [17], [8], [10], [79],
  [10], [Sara Ostafiev], [2014], [Trojanska Hästen], [], [16], [25], [], [], [25], [11], [77],
  [11], [Edonna Abitov], [2013], [SS 4 Springare], [17], [], [15], [10], [22], [10], [], [74],
  [12], [Sahana Viswanath], [2017], [Kristallens SK], [8], [8], [11], [19], [21], [], [5], [72],
  [13], [Ece Yigit], [2014], [Eskilstuna SK], [], [25], [24], [], [], [22], [], [71],
  [14], [Cristina Ostafiev], [2011], [Trojanska Hästen], [], [], [25], [], [], [25], [5], [55],
  [15], [Elise Najafi], [2015], [Wasa SK], [], [10], [], [18], [6], [], [19], [53],
  [16], [Tuva Schmalholz], [2011], [Wasa SK], [25], [25], [], [], [], [], [], [50],
  [17], [Ella Svartengren], [2016], [Trojanska Hästen], [5], [], [14], [16], [10], [5], [], [50],
  [18], [Sofia Lazovskaya], [2011], [Kristallens SK], [20], [], [8], [11], [], [9], [], [48],
  [19], [Josefina Hellstrand], [2010], [Trojanska Hästen], [19], [], [18], [], [], [11], [], [48],
  [20], [Lily Popovics], [2011], [SS 4 Springare], [15], [], [], [5], [25], [], [], [45],
  [21], [Ece Gültekin], [2010], [Kristallens SK], [24], [], [], [], [], [20], [], [44],
  [22], [Emma Nilsson Lundberg], [2013], [Wasa SK], [7], [], [], [11], [], [13], [], [31],
  [23], [Eli Möller], [2013], [Tyresö SK], [11], [14], [6], [], [], [], [], [31],
  [24], [Victoria Loboda], [2017], [SS 4 Springare], [6], [5], [10], [], [], [7], [], [28],
  [25], [Sriharshini Prakash], [2016], [SK Passanten], [7], [], [], [13], [8], [], [], [28],
  [26], [Sierra Prashant Joshi], [2013], [Kristallens SK], [], [], [8], [6], [], [8], [5], [27],
  [27], [Aryahi Krishna Chandragiri], [2012], [SK Rockaden Sthlm], [], [], [], [25], [], [], [], [25],
  [28], [Nova Golkar], [2015], [Trojanska Hästen], [11], [], [14], [], [], [], [], [25],
  [29], [Liyaasri Naveen], [2014], [Nacka-Värmdö SK], [], [], [25], [], [], [], [], [25],
  [30], [Ida Redtzer], [2011], [Trojanska Hästen], [13], [], [11], [], [], [], [], [24],
  [31], [Hanna Halubouskaya], [2014], [Farsta SK], [], [7], [], [4], [5], [6], [], [22],
  [32], [Alexandra Hamilton], [2014], [Kristallens SK], [5], [8], [9], [], [], [], [], [22],
  [33], [Elvira Öhrn], [2014], [Trojanska Hästen], [12], [], [10], [], [], [], [], [22],
  [34], [Aylin Bakhridinova], [2016], [SS 4 Springare], [5], [7], [], [], [], [5], [5], [22],
  [35], [Nellie Ståhl], [2010], [Jönköpings SS], [21], [], [], [], [], [], [], [21],
  [36], [Melisa Fedorczuk], [2015], [Tyresö SK], [5], [9], [], [], [], [5], [], [19],
  [37], [Miona Obradovic], [2013], [Täby SK], [], [], [19], [], [], [], [], [19],
  [38], [Gayathri Sreekanth], [2014], [SK Rockaden Sthlm], [], [], [19], [], [], [], [], [19],
  [39], [Alexandra Burmakina], [2013], [Farsta SK], [], [], [], [], [10], [], [8], [18],
  [40], [Hiba Sayghani], [2013], [Trojanska Hästen], [18], [], [], [], [], [], [], [18],
  [41], [Adiva Khan], [2017], [Kista SC KFUM Schacksektion], [], [], [], [7], [6], [5], [], [18],
  [42], [Emmy Mai], [2018], [Kristallens SK], [6], [], [], [4], [7], [], [], [17],
  [43], [Sophia Sun Mossberg], [2014], [Lidingö SS], [], [6], [10], [], [], [], [], [16],
  [44], [Nithyasri Venkata Ommi], [2019], [Farsta SK], [], [], [], [6], [5], [5], [], [16],
  [45], [Aleksandra Loboda], [2020], [SS 4 Springare], [5], [5], [], [], [], [5], [], [15],
  [46], [Shreenika Sudarsan], [2017], [Wasa SK], [], [], [], [9], [5], [], [], [14],
  [47], [Mila Lovisa Jonsson], [2019], [SS 4 Springare], [], [6], [], [8], [], [], [], [14],
  [48], [Vendela Landelius], [2011], [Tyresö SK], [8], [5], [], [], [], [], [], [13],
  [49], [Annie Saukkoriipi Af Ekenstam], [2014], [Trojanska Hästen], [7], [], [6], [], [], [], [], [13],
  [50], [Edda Alvarez], [2017], [SK Rockaden Sthlm], [5], [], [], [], [8], [], [], [13],
  [51], [Victoire Bogey], [2017], [SS 4 Springare], [], [], [8], [], [], [5], [], [13],
  [52], [Thea Karlsson], [2010], [Kristallens SK], [], [], [], [], [11], [], [], [11],
  [53], [Gillis Spångberg], [2013], [Trojanska Hästen], [], [], [11], [], [], [], [], [11],
  [54], [Denise Alfredsson], [2018], [Trojanska Hästen], [], [5], [6], [], [], [], [], [11],
  [55], [Dhriti Vignesh], [2015], [Järfälla SS], [], [], [10], [], [], [], [], [10],
  [56], [Alexis Tomtlund], [2014], [SK Rockaden Sthlm], [10], [], [], [], [], [], [], [10],
  [57], [Zoe Schäffler], [2016], [Kristallens SK], [10], [], [], [], [], [], [], [10],
  [58], [Emilia Alonso Alonso], [2016], [SS 4 Springare], [], [], [5], [], [], [5], [], [10],
  [59], [Liv Löwe Cribäck], [2019], [Kristallens SK], [5], [], [], [], [], [5], [], [10],
  [60], [Deesha Dinesh], [2018], [Trojanska Hästen], [], [], [5], [], [5], [], [], [10],
  [61], [Alice Saukoriipi af Ekenstam], [2019], [Trojanska Hästen], [5], [], [5], [], [], [], [], [10],
  [62], [Ingibjörg Ylfa Fannarsdóttir], [2013], [Uppsala SSS], [], [], [9], [], [], [], [], [9],
  [63], [Miyu Mori], [2013], [SIS Chess], [], [], [], [8], [], [], [], [8],
  [64], [Vanda Asadi], [2016], [Trojanska Hästen], [], [], [8], [], [], [], [], [8],
  [65], [Negan Sayghani], [2014], [Trojanska Hästen], [8], [], [], [], [], [], [], [8],
  [66], [Alicia Stroganova], [2015], [SS 4 Springare], [], [], [], [], [], [8], [], [8],
  [67], [Aniya Rahmani], [2010], [Upplands Väsby SK], [], [], [], [], [], [7], [], [7],
  [68], [Isabel Nilvebrant], [2014], [Trojanska Hästen], [], [], [7], [], [], [], [], [7],
  [69], [Julie Thörne], [2014], [Djurgårdens IF Schack], [], [], [7], [], [], [], [], [7],
  [70], [Sofia Assal], [2016], [Wasa SK], [], [], [], [], [7], [], [], [7],
  [71], [Mara Pote], [2019], [SS 4 Springare], [], [], [7], [], [], [], [], [7],
  [72], [Maria Waern], [2018], [SIS Chess], [], [], [], [6], [], [], [], [6],
  [73], [Hisha Varanasi], [2016], [Trojanska Hästen], [], [], [6], [], [], [], [], [6],
  [74], [Esmée Thander], [2016], [Farsta SK], [], [], [], [], [], [6], [], [6],
  [75], [Nathalie Biström], [2009], [Trojanska Hästen], [], [], [5], [], [], [], [], [5],
  [76], [Sophie Baginski], [2011], [Wasa SK], [], [], [], [], [5], [], [], [5],
  [77], [Artemis Maraveliotakis], [2012], [Wasa SK], [], [], [5], [], [], [], [], [5],
  [78], [Anastasiia Kravchenko], [2013], [Täby SK], [], [], [5], [], [], [], [], [5],
  [79], [Gabriella Bergqvist Hult], [2015], [Essingeskolan SBs Falkar], [], [5], [], [], [], [], [], [5],
  [80], [Anastasia Nikulin], [2017], [SIS Chess], [], [], [], [5], [], [], [], [5],
  [81], [Alicia Bergman], [2016], [Trojanska Hästen], [], [], [5], [], [], [], [], [5],
  [82], [Diana Nikulin], [2019], [SIS Chess], [], [], [], [5], [], [], [], [5],
  [83], [Elisa Stroganova], [2017], [SS 4 Springare], [], [], [], [], [], [5], [], [5],
  [84], [Pippa Meijer], [2017], [SS 4 Springare], [], [], [], [], [], [5], [], [5],
  [85], [Defna Karaman], [2019], [SS 4 Springare], [], [], [], [], [], [5], [], [5],
  [86], [Ellie Condro], [2020], [SS 4 Springare], [], [], [], [], [], [5], [], [5],
  [87], [Kinjal Singh], [2017], [SS 4 Springare], [], [], [], [], [], [5], [], [5],
  [88], [Nomie Condro], [2018], [SS 4 Springare], [], [], [], [], [], [5], [], [5],
  [89], [Jamila Khalaf], [2020], [SS 4 Springare], [], [], [], [], [], [5], [], [5],
  [90], [Lovisa Karlsson], [2019], [SK Rockaden Sthlm], [], [], [], [], [], [5], [], [5],
  [91], [Vilma Nilsson], [2017], [Tuffa Tornet], [], [], [5], [], [], [], [], [5],
  [92], [Ella Ankri Norrman], [2018], [Tuffa Tornet], [], [], [5], [], [], [], [], [5],
  [93], [Iris Ruud], [2018], [Täby SK], [], [], [5], [], [], [], [], [5],
  [94], [Emili Laanemaa], [2015], [Kristallens SK], [5], [], [], [], [], [], [], [5],
  [95], [Rori Campbell Peoples], [2017], [Kristallens SK], [5], [], [], [], [], [], [], [5],
  [96], [Lucy Åberg Widén], [2017], [Kristallens SK], [5], [], [], [], [], [], [], [5],
  [97], [Lara Tarcea], [2018], [Kristallens SK], [5], [], [], [], [], [], [], [5],
  [98], [Clara Smith], [2014], [Trojanska Hästen], [], [], [4], [], [], [], [], [4],
)]
#set text(9pt, font: "Roboto", weight: "medium")
#linebreak()
#columns(2)[
+ Tjejträffen 2026
+ Tyresö JGP 2026
+ Trojanska Hästen JGP 2026 Vår
#colbreak()
4. SIS Chess JGP 2026
5. Wasa JGP 2026
6. SS 4 Springare JGP 2026
7. Junior-DM i Snabbschack 2026
]
#include "rules.typ"
#linebreak()

        #show link: set text(blue)
 \ \
        Synpunkter / Comments: #link("mailto:bganesh@gmail.com")[Ganesh Srinivasson]
        
