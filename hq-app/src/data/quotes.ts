export interface Quote {
  text: string
  author: string
}

// ~25 quotes mixing Bruce Lee, Bob Marley, Marcus Aurelius, Proverbs/Bible,
// Buddhist texts, Einstein, Eric Thomas, Nietzsche, Emerson, Japanese proverbs,
// Kobe Bryant, Muhammad Ali. Seeded by day-of-year so it holds all day.
export const QUOTES: Quote[] = [
  { text: 'Do not pray for an easy life, pray for the strength to endure a difficult one.', author: 'Bruce Lee' },
  { text: 'Absorb what is useful, discard what is not, add what is uniquely your own.', author: 'Bruce Lee' },
  { text: 'The greatness of a man is not in how much wealth he acquires, but in his integrity.', author: 'Bob Marley' },
  { text: 'You never know how strong you are until being strong is your only choice.', author: 'Bob Marley' },
  { text: 'You have power over your mind — not outside events. Realize this, and you will find strength.', author: 'Marcus Aurelius' },
  { text: 'Waste no more time arguing about what a good man should be. Be one.', author: 'Marcus Aurelius' },
  { text: 'The impediment to action advances action. What stands in the way becomes the way.', author: 'Marcus Aurelius' },
  { text: 'Commit your work to the Lord, and your plans will be established.', author: 'Proverbs 16:3' },
  { text: 'The plans of the diligent lead surely to abundance, but everyone who is hasty comes only to poverty.', author: 'Proverbs 21:5' },
  { text: 'Iron sharpens iron, and one man sharpens another.', author: 'Proverbs 27:17' },
  { text: 'What we think, we become. All that we are arises with our thoughts.', author: 'Buddha' },
  { text: 'Do not dwell in the past, do not dream of the future, concentrate the mind on the present moment.', author: 'Buddha' },
  { text: 'Life is like riding a bicycle. To keep your balance, you must keep moving.', author: 'Albert Einstein' },
  { text: 'A person who never made a mistake never tried anything new.', author: 'Albert Einstein' },
  { text: 'When you want to succeed as bad as you want to breathe, then you will be successful.', author: 'Eric Thomas' },
  { text: 'The pain you feel today is the strength you feel tomorrow.', author: 'Eric Thomas' },
  { text: 'That which does not kill us makes us stronger.', author: 'Friedrich Nietzsche' },
  { text: 'He who has a why to live can bear almost any how.', author: 'Friedrich Nietzsche' },
  { text: 'What lies behind us and what lies before us are tiny matters compared to what lies within us.', author: 'Ralph Waldo Emerson' },
  { text: 'Do not go where the path may lead, go instead where there is no path and leave a trail.', author: 'Ralph Waldo Emerson' },
  { text: 'Fall down seven times, stand up eight.', author: 'Japanese Proverb' },
  { text: 'Vision without action is a daydream. Action without vision is a nightmare.', author: 'Japanese Proverb' },
  { text: 'Everything negative — pressure, challenges — is all an opportunity for me to rise.', author: 'Kobe Bryant' },
  { text: 'The most important thing is to try and inspire people so they can be great at whatever they want to do.', author: 'Kobe Bryant' },
  { text: "Don't count the days, make the days count.", author: 'Muhammad Ali' },
  { text: "It's the repetition of affirmations that leads to belief. And once that belief becomes a conviction, things begin to happen.", author: 'Muhammad Ali' },
]

// Same quote all day; rotates at local midnight.
export function quoteOfDay(now: Date = new Date()): Quote {
  const start = new Date(now.getFullYear(), 0, 0)
  const diff = now.getTime() - start.getTime()
  const dayOfYear = Math.floor(diff / 86_400_000)
  return QUOTES[dayOfYear % QUOTES.length]
}
