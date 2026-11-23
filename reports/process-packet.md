# Process-reward annotation packet

Label each step good / neutral / bad up to the first bad step (see `guidelines/process-reward-v1.md`). Do not look at `data/process/hidden.jsonl`.

## ps-01

**Problem.** A cafe sells coffee at $3.50 and muffins at $1.75. Ana buys 4 coffees and 3 muffins and pays with a $20 bill. How much change does she get?

1. Coffees cost 4 x 3.50. `4*3.50 = 14`
2. Muffins cost 3 x 1.75. `3*1.75 = 5.25`
3. Total is 14 + 5.25. `14+5.25 = 19.25`
4. Change is 20 - 19.25. `20-19.25 = 0.75`
5. So Ana gets $0.75 in change.

## ps-02

**Problem.** A cafe sells coffee at $3.50 and muffins at $1.75. Ana buys 4 coffees and 3 muffins and pays with a $20 bill. How much change does she get?

1. Coffees cost 4 x 3.50. `4*3.50 = 14`
2. Muffins cost 3 x 1.75. `3*1.75 = 5.75`
3. Total is 14 + 5.75. `14+5.75 = 19.75`
4. Change is 20 - 19.75. `20-19.75 = 0.25`
5. So Ana gets $0.25 in change.

## ps-03

**Problem.** A cafe sells coffee at $3.50 and muffins at $1.75. Ana buys 4 coffees and 3 muffins and pays with a $20 bill. How much change does she get?

1. Coffees cost 4 x 3.50. `4*3.50 = 15`
2. Muffins cost 3 x 1.75. `3*1.75 = 4.25`
3. Total is 15 + 4.25. `15+4.25 = 19.25`
4. Change is 20 - 19.25. `20-19.25 = 0.75`
5. So Ana gets $0.75 in change.

## ps-04

**Problem.** A train leaves at 09:40 and the journey normally takes 2 h 35 min. Today it is delayed by 25 min. At what time does it arrive?

1. Total travel time is 2 h 35 min plus the 25 min delay, in minutes 155 + 25. `155+25 = 180`
2. 180 minutes is 3 hours.
3. 09:40 plus 3 hours is 12:40.
4. The train arrives at 12:40.

## ps-05

**Problem.** A train leaves at 09:40 and the journey normally takes 2 h 35 min. Today it is delayed by 25 min. At what time does it arrive?

1. The journey takes 2 h 35 min, which is 155 minutes. `2*60+35 = 155`
2. A delay shortens the remaining journey, so the travel time is 155 - 25. `155-25 = 130`
3. 130 minutes is 2 h 10 min.
4. 09:40 plus 2 h 10 min is 11:50.
5. The train arrives at 11:50.

## ps-06

**Problem.** A shirt costs $40. It is discounted 25%, then 10% sales tax is added to the discounted price. What is the final price?

1. A 25% discount and a 10% tax combine to a net 15% discount.
2. So the price is 40 x 0.85. `40*0.85 = 34`
3. The final price is $34.

## ps-07

**Problem.** A shirt costs $40. It is discounted 25%, then 10% sales tax is added to the discounted price. What is the final price?

1. After the discount the price is 40 x 0.75. `40*0.75 = 30`
2. Adding 10% tax gives 30 x 1.10. `30*1.10 = 33`
3. The final price is $33.

## ps-08

**Problem.** A rectangle has a perimeter of 30 cm and its length is twice its width. What is its area?

1. Let the width be w, so the length is 2w.
2. Perimeter: 2(2w + w) = 30, so 6w = 30.
3. w = 30 / 6. `30/6 = 5`
4. The length is 2 x 5. `2*5 = 10`
5. Area = 10 x 5. `10*5 = 50`
6. The area is 50 cm^2.

## ps-09

**Problem.** A rectangle has a perimeter of 30 cm and its length is twice its width. What is its area?

1. Let the width be w, so the length is 2w.
2. The perimeter is length plus width, so 2w + w = 30, giving 3w = 30.
3. w = 30 / 3. `30/3 = 10`
4. The length is 2 x 10. `2*10 = 20`
5. Area = 20 x 10. `20*10 = 200`
6. The area is 200 cm^2.

## ps-10

**Problem.** Leo's average over 4 tests is 80. After a fifth test his average is 82. What did he score on the fifth test?

1. The first 4 tests total 4 x 80. `4*80 = 320`
2. All 5 tests total 5 x 82. `5*82 = 410`
3. The fifth score is 410 - 320. `410-320 = 90`
4. Leo scored 90.

## ps-11

**Problem.** Leo's average over 4 tests is 80. After a fifth test his average is 82. What did he score on the fifth test?

1. The average rose by 82 - 80 points. `82-80 = 2`
2. So the fifth test was just 2 points above the new average: 82 + 2. `82+2 = 84`
3. Leo scored 84.
