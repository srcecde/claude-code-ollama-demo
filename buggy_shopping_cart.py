class ShoppingCart:
    def __init__(self):
        self.items = []
        self.discount_code = None

    def add_item(self, name, price, quantity):
        # Bug 1: Doesn't check if item already exists, creates duplicates
        item = {"name": name, "price": price, "quantity": quantity}
        self.items.append(item)

    def remove_item(self, name):
        # Bug 2: Modifying list while iterating - will skip items
        for item in self.items:
            if item["name"] == name:
                self.items.remove(item)

    def get_subtotal(self):
        total = 0
        for item in self.items:
            total += item["price"] * item["quantity"]
        return total

    def apply_discount(self, code):
        # Bug 3: Doesn't validate discount code, silently accepts invalid codes
        self.discount_code = code

    def get_discount_amount(self):
        subtotal = self.get_subtotal()
        if self.discount_code == "SAVE10":
            return subtotal * 0.10
        elif self.discount_code == "SAVE20":
            return subtotal * 0.20
        # Returns 0 for invalid codes - user thinks discount applied but it wasn't
        return 0

    def get_total(self):
        return self.get_subtotal() - self.get_discount_amount()

    def checkout(self):
        if len(self.items) == 0:
            return "Cart is empty"
        total = self.get_total()
        if total < 0:
            total = 0
        # Missing proper currency formatting
        return f"Total: ${total}"


# Test the cart
cart = ShoppingCart()
cart.add_item("Laptop", 999.99, 1)
cart.add_item("Mouse", 29.99, 2)
cart.add_item("Keyboard", 79.99, 1)

print("Items:", len(cart.items))
print("Subtotal:", cart.get_subtotal())

cart.apply_discount("SAVE20")
print("Discount:", cart.get_discount_amount())
print("Total:", cart.get_total())

print(cart.checkout())
