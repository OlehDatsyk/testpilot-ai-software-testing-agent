import { cartTotal, formatCurrency } from './cart.js';

describe('cart', () => {
  it('sums line items', () => {
    expect(cartTotal([{ price: 1.5, quantity: 2 }, { price: 3, quantity: 1 }])).toBe(6);
  });

  it('formats euros', () => {
    expect(formatCurrency(3, 'EUR')).toBe('€3.00');
  });
});
