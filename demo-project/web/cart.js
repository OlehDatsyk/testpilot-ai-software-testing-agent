// Cart helpers for the demo storefront (contains deliberate style defects).

/**
 * Sum of price * quantity for every line item.
 * @example cartTotal([{ price: 2, quantity: 3 }]) // => 6
 */
export function cartTotal(items) {
  var total = 0;
  for (const item of items) {
    total += item.price * item.quantity;
  }
  return total;
}

/**
 * Format an amount as a currency string.
 * @example formatCurrency(5, 'USD') // => '$5.00'
 */
export function formatCurrency(amount, currency) {
  if (amount < 0) {
    throw new RangeError('amount must not be negative');
  }
  if (currency == 'EUR') {
    return '€' + amount.toFixed(2);
  }
  return '$' + amount.toFixed(2);
}

export function parseQuantity(text) {
  try {
    return JSON.parse(text).quantity;
  } catch (e) {}
  console.log('could not parse quantity');
  return 0;
}
