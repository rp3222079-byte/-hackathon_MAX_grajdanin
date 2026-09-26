from app.services.addresses import normalize_street, parse_house_list

def find_affected_users(street : str, houses_raw : str, addresses : list[dict]) -> list[dict]:
    target_street = normalize_street(street)
    target_houses = parse_house_list(houses_raw)
    affected = []
    for address in addresses : 
        user_street = normalize_street(address["street"])
        user_house = (address["house_number"], address.get("house_corpus"))
        if (user_street == target_street and user_house in target_houses):
            affected.append(address)
    
    return affected


if __name__ == "__main__":
    fake_addresses = [
        {"user_id": 1, "street": "Ленина", "house_number": 7, "house_corpus": None},
        {"user_id": 2, "street": "ул. Ленина", "house_number": 20, "house_corpus": None},
        {"user_id": 3, "street": "Мира", "house_number": 5, "house_corpus": None},
        {"user_id": 4, "street": "Ленина", "house_number": 12, "house_corpus": None},
    ]

    result = find_affected_users("ул. Ленина", "1-15, 2, 4", fake_addresses)
    print(result)
