# locustfile.py - нагрузочные тесты для курсача "Навигатор" (Navigator.API)
# запуск с интерфейсом: locust -f locustfile.py --host=http://127.0.0.1:5000
# потом открыть http://localhost:8089, выставить 100 юзеров и запустить
# запуск без интерфейса: locust -f locustfile.py --host=http://127.0.0.1:5000 --headless -u 100 -r 10 -t 3m

from locust import HttpUser, TaskSet, SequentialTaskSet, task, between
from faker import Faker
import random

fake = Faker('ru_RU')

# слова для поиска, обычные, как их вводят живые люди
SEARCH_WORDS = ["кафе", "парк", "музей", "метро", "аптека", "магазин", "отель", "площадь", "театр", "школа"]

MAX_POINT_ID = 180  # столько точек сейчас в базе
MAX_CATEGORY_ID = 8  # а столько категорий


def random_password():
    # пароль по требованиям апи: маленькие + большая буквы и цифра, минимум 8 символов
    return "Pass%dAa" % random.randint(10000, 99999)


def random_phone():
    # телефон строго в формате +7 и 10 цифр, иначе апи ругается
    return "+7%010d" % random.randint(0, 9999999999)


def moscow_coords():
    # случайная точка где-то по Москве
    return round(random.uniform(55.5, 56.0), 6), round(random.uniform(37.3, 37.9), 6)


def register(taskset):
    # регистрируем нового пользователя и запоминаем токен на юзере,
    # чтобы не регистрироваться перед каждым запросом
    user = taskset.user
    if getattr(user, "token", None):
        taskset.client.headers.update({"Authorization": "Bearer " + user.token})
        return True
    payload = {
        "fio": fake.name(),
        "email": "load%d_%s@example.com" % (random.randint(1, 999999), fake.user_name()),
        "password": random_password(),
        "phone": random_phone(),
    }
    r = taskset.client.post("/api/auth/register", json=payload, name="/api/auth/register")
    if r.status_code != 200:
        return False
    try:
        user.token = r.json()["data"]["token"]
    except (ValueError, KeyError, TypeError):
        return False
    taskset.client.headers.update({"Authorization": "Bearer " + user.token})
    return True


def ok(response, what):
    # проверяем ответ апи: должен быть 200 и success=true, иначе помечаем как fail
    try:
        body = response.json()
    except ValueError:
        response.failure(what + ": пришел не json")
        return None
    if response.status_code != 200 or not body.get("success"):
        response.failure("%s: status=%s" % (what, response.status_code))
        return None
    response.success()
    return body.get("data")


class BrowseBehavior(TaskSet):
    # гость без регистрации, просто смотрит карту. 5 задач на чтение

    @task(10)
    def categories(self):
        with self.client.get("/api/categories", name="/api/categories", catch_response=True) as r:
            ok(r, "categories")

    @task(10)
    def category_card(self):
        cat_id = random.randint(1, MAX_CATEGORY_ID)
        with self.client.get("/api/categories/%d" % cat_id, name="/api/categories/[id]", catch_response=True) as r:
            if r.status_code == 404:
                r.success()  # такой категории нет, это нормально
            else:
                ok(r, "category_card")

    @task(10)
    def points_list(self):
        params = {"Page": random.randint(1, 9), "PageSize": random.choice([5, 10, 20])}
        if random.random() < 0.5:
            params["CategoryId"] = random.randint(1, MAX_CATEGORY_ID)  # иногда с фильтром
        with self.client.get("/api/points", params=params, name="/api/points", catch_response=True) as r:
            ok(r, "points_list")

    @task(10)
    def point_card(self):
        point_id = random.randint(1, MAX_POINT_ID)
        with self.client.get("/api/points/%d" % point_id, name="/api/points/[id]", catch_response=True) as r:
            if r.status_code == 404:
                r.success()
            else:
                ok(r, "point_card")

    @task(10)
    def points_search(self):
        with self.client.get("/api/points/search", params={"query": random.choice(SEARCH_WORDS)},
                              name="/api/points/search", catch_response=True) as r:
            ok(r, "points_search")


class MemberActions(TaskSet):
    # залогиненный пользователь. читает много, пишет мало:
    # у чтения вес 10, у записи 1-2, то есть чтение чаще минимум в 5 раз

    def on_start(self):
        register(self)

    @task(10)
    def my_profile(self):
        if not register(self):
            return
        with self.client.get("/api/auth/me", name="/api/auth/me", catch_response=True) as r:
            ok(r, "me")

    @task(10)
    def points_list(self):
        with self.client.get("/api/points", params={"Page": random.randint(1, 9), "PageSize": 20},
                              name="/api/points", catch_response=True) as r:
            ok(r, "points_list")

    @task(10)
    def routes_history(self):
        if not register(self):
            return
        with self.client.get("/api/routes/history", name="/api/routes/history", catch_response=True) as r:
            ok(r, "history")

    @task(10)
    def poi_favorites(self):
        if not register(self):
            return
        with self.client.get("/api/favorites/poi", name="/api/favorites/poi", catch_response=True) as r:
            ok(r, "fav_poi")

    @task(10)
    def notifications(self):
        if not register(self):
            return
        with self.client.get("/api/notifications", name="/api/notifications", catch_response=True) as r:
            ok(r, "notifications")

    @task(2)
    def create_route(self):
        # сохранить маршрут в историю
        if not register(self):
            return
        s_lat, s_lon = moscow_coords()
        e_lat, e_lon = moscow_coords()
        payload = {
            "startLat": s_lat, "startLon": s_lon,
            "endLat": e_lat, "endLon": e_lon,
            "startAddress": fake.street_address(),
            "endAddress": fake.street_address(),
            "transportType": random.choice(["auto", "walking", "masstransit"]),
        }
        with self.client.post("/api/routes", json=payload, name="/api/routes [POST]", catch_response=True) as r:
            ok(r, "create_route")

    @task(1)
    def build_route(self):
        # построить маршрут на карте
        if not register(self):
            return
        s_lat, s_lon = moscow_coords()
        e_lat, e_lon = moscow_coords()
        payload = {
            "startLat": s_lat, "startLon": s_lon,
            "endLat": e_lat, "endLon": e_lon,
            "transportType": random.choice(["auto", "walking"]),
        }
        with self.client.post("/api/routes/build", json=payload, name="/api/routes/build", catch_response=True) as r:
            ok(r, "build_route")

    @task(1)
    def add_favorite(self):
        # добавить случайную точку в избранное
        if not register(self):
            return
        poi_id = random.randint(1, MAX_POINT_ID)
        with self.client.post("/api/favorites/poi/%d" % poi_id, name="/api/favorites/poi/[id] [POST]",
                               catch_response=True) as r:
            ok(r, "add_favorite")

    @task(1)
    def log_event(self):
        # кинуть событие в аналитику
        if not register(self):
            return
        payload = {
            "eventType": random.choice(["route_built", "poi_viewed", "search"]),
            "eventData": fake.sentence(nb_words=4),
            "deviceType": random.choice(["web", "android", "ios"]),
        }
        with self.client.post("/api/alibi/log", json=payload, name="/api/alibi/log", catch_response=True) as r:
            ok(r, "log_event")


class UserJourney(SequentialTaskSet):
    # сценарий живого пользователя строго по шагам:
    # список -> карточка -> поиск -> построил и сохранил -> история -> избранное
    # в отличие от TaskSet тут порядок фиксированный, веса не работают

    def on_start(self):
        register(self)

    @task
    def step1_open_list(self):
        with self.client.get("/api/points", params={"Page": 1, "PageSize": 20},
                              name="/api/points", catch_response=True) as r:
            ok(r, "journey_list")

    @task
    def step2_open_card(self):
        point_id = random.randint(1, MAX_POINT_ID)
        with self.client.get("/api/points/%d" % point_id, name="/api/points/[id]", catch_response=True) as r:
            if r.status_code == 404:
                r.success()
            else:
                ok(r, "journey_card")

    @task
    def step3_search(self):
        with self.client.get("/api/points/search", params={"query": random.choice(SEARCH_WORDS)},
                              name="/api/points/search", catch_response=True) as r:
            ok(r, "journey_search")

    @task
    def step4_build_and_save(self):
        if not register(self):
            return
        s_lat, s_lon = moscow_coords()
        e_lat, e_lon = moscow_coords()
        with self.client.post("/api/routes/build",
                               json={"startLat": s_lat, "startLon": s_lon, "endLat": e_lat,
                                     "endLon": e_lon, "transportType": "auto"},
                               name="/api/routes/build", catch_response=True) as r:
            ok(r, "journey_build")
        with self.client.post("/api/routes",
                               json={"startLat": s_lat, "startLon": s_lon, "endLat": e_lat,
                                     "endLon": e_lon, "startAddress": fake.street_address(),
                                     "endAddress": fake.street_address(), "transportType": "auto"},
                               name="/api/routes [POST]", catch_response=True) as r:
            ok(r, "journey_save")

    @task
    def step5_history(self):
        if not register(self):
            return
        with self.client.get("/api/routes/history", name="/api/routes/history", catch_response=True) as r:
            ok(r, "journey_history")

    @task
    def step6_favorite(self):
        if not register(self):
            return
        poi_id = random.randint(1, MAX_POINT_ID)
        with self.client.post("/api/favorites/poi/%d" % poi_id, name="/api/favorites/poi/[id] [POST]",
                               catch_response=True) as r:
            ok(r, "journey_fav")


class GuestUser(HttpUser):
    # гость только смотрит, ничего не пишет
    tasks = [BrowseBehavior]
    wait_time = between(1, 3)


class MemberUser(HttpUser):
    # залогиненный: в основном читает (MemberActions), иногда идет по сценарию (UserJourney)
    tasks = {MemberActions: 3, UserJourney: 1}
    wait_time = between(1, 3)
