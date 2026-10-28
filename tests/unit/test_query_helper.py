import pytest
from sqlalchemy import ForeignKey, create_engine
from sqlalchemy.orm import Session, aliased, declarative_base, load_only, relationship, selectinload
from sqlalchemy.pool import StaticPool
from sqlalchemy import Column, Integer, String

from services.mysql import query, query_sync

Base = declarative_base()


class Parent(Base):
    __tablename__ = "parents"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    note = Column(String)
    children = relationship("Child", back_populates="parent")


class Child(Base):
    __tablename__ = "children"
    id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, ForeignKey("parents.id"))
    label = Column(String)
    parent = relationship("Parent", back_populates="children")


@pytest.fixture
def db():
    eng = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add_all([Parent(id=1, name="a", note="n1"), Parent(id=2, name="b", note="n2")])
        s.add_all([Child(id=10, parent_id=1, label="x"), Child(id=11, parent_id=2, label="y")])
        s.commit()
        yield s


class AsyncWrap:
    """Async facade over a sync Session (no aiosqlite dependency needed)."""

    def __init__(self, s: Session):
        self.s = s

    async def execute(self, stmt):
        return self.s.execute(stmt)


async def run(kind: str, db: Session, *args, **kw):
    return await query(AsyncWrap(db), *args, **kw) if kind == "async" else query_sync(db, *args, **kw)


@pytest.fixture(params=["async", "sync"])
def kind(request):
    return request.param


async def test_entity_default_and_scalars(kind, db):
    rows = await run(kind, db, Parent)
    assert [p.name for p in rows] == ["a", "b"]
    assert await run(kind, db, Parent, columns=(Parent.name,)) == ["a", "b"]


async def test_multi_columns_return_rows(kind, db):
    rows = await run(kind, db, Parent, columns=(Parent.id, Parent.name), order_by=(Parent.id,))
    assert [tuple(r) for r in rows] == [(1, "a"), (2, "b")]


async def test_filters_order_limit_offset_fetch_one(kind, db):
    assert await run(kind, db, Parent, columns=(Parent.id,), order_by=(Parent.id.desc(),), limit=1, offset=1) == [1]
    one = await run(kind, db, Parent, filters=(Parent.id == 2,), fetch_one=True)
    assert one.name == "b"
    assert await run(kind, db, Parent, columns=(Parent.id,), order_by=(Parent.id,), fetch_one=True) == 1
    row = await run(kind, db, Parent, columns=(Parent.id, Parent.name), order_by=(Parent.id,), fetch_one=True)
    assert tuple(row) == (1, "a")
    assert await run(kind, db, Parent, filters=(Parent.id == 99,), fetch_one=True) is None


async def test_join_shapes(kind, db):
    rel = await run(kind, db, Parent, columns=(Parent.id,), joins=(Parent.children,), order_by=(Parent.id,))
    explicit = await run(kind, db, Parent, columns=(Parent.id,), joins=((Child, Child.parent_id == Parent.id),))
    outer = await run(
        kind,
        db,
        Parent,
        columns=(Parent.id,),
        joins=((Child, (Child.parent_id == Parent.id) & (Child.id == 10), True),),
        order_by=(Parent.id,),
    )
    assert rel == [1, 2] and sorted(explicit) == [1, 2] and outer == [1, 2]


async def test_load_only_in_options_keeps_entity_and_relation(kind, db):
    db.expunge_all()
    rows = await run(
        kind,
        db,
        Parent,
        options=(load_only(Parent.name), selectinload(Parent.children).load_only(Child.label)),
        order_by=(Parent.id,),
    )
    from sqlalchemy import inspect

    assert isinstance(rows[0], Parent)
    assert "note" in inspect(rows[0]).unloaded
    assert [c.label for c in rows[0].children] == ["x"]


async def test_duplicate_keys_are_labelled(kind, db):
    row = await run(
        kind,
        db,
        Parent,
        columns=(Parent.id, Parent.name, Child.id),
        joins=(Parent.children,),
        order_by=(Parent.id,),
        fetch_one=True,
    )
    assert (row.parents_id, row.name, row.children_id) == (1, "a", 10)
    assert tuple(row) == (1, "a", 10)


async def test_explicit_label_untouched(kind, db):
    row = await run(
        kind,
        db,
        Parent,
        columns=(Parent.id, Child.id.label("child_pk")),
        joins=(Parent.children,),
        order_by=(Parent.id,),
        fetch_one=True,
    )
    assert (row.id, row.child_pk) == (1, 10)


async def test_same_table_joined_twice_via_alias(kind, db):
    other = aliased(Parent)
    row = await run(
        kind,
        db,
        Parent,
        columns=(Parent.name, other.name.label("other_name")),
        joins=((other, other.id == Parent.id + 1),),
        order_by=(Parent.id,),
        fetch_one=True,
    )
    assert (row.name, row.other_name) == ("a", "b")
