# Linkedin-bot-

Linkedin Bot that will search for jobs and alert me for new openings every hour.

Here is the diagram: 

      JOB BOT
                      │
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
    LinkedIn       Indeed         Dice
        │             │             │
        └─────────────┼─────────────┘
                      ↓
                JOB DATABASE
                      ↓
                MATCH SCORING
                      ↓
             ┌────────┴────────┐
             ↓                 ↓
         HIGH MATCH       LOW MATCH
             ↓
          ALERT 
