"""
Copyright 2019 Goldman Sachs.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""

import logging
from typing import List, Dict

from gs_quant.api.gs.groups import GsGroupsApi
from gs_quant.api.gs.users import GsUsersApi
from gs_quant.errors import MqValueError, MqRequestError
from gs_quant.target.common import Entitlements as TargetEntitlements
from gs_quant.target.groups import Group as TargetGroup

_logger = logging.getLogger(__name__)


class User:
    def __init__(self,
                 user_id: str,
                 name: str,
                 email: str,
                 company: str):
        self.__id = user_id
        self.__email = email
        self.__name = name
        self.__company = company

    def __eq__(self, other):
        return self.id == other.id

    def __hash__(self):
        return hash(self.id) ^ hash(self.name)

    @property
    def id(self):
        return self.__id

    @property
    def email(self):
        return self.__email

    @property
    def name(self):
        return self.__name

    @property
    def company(self):
        return self.__company

    @classmethod
    def get(cls,
            user_id: str = None,
            name: str = None,
            email: str = None):
        """
        Resolve a user ID, name, email, and/or company into a single User object

        :param user_id: User's unique GS Marquee User ID
        :param name: User's name (formatted 'Last Name, First Name')
        :param email: User's email address
        :return: A Marquee User object that corresponds to requested parameters
        """
        if all(arg is None for arg in [user_id, name, email]):
            raise MqValueError('Please specify a user id, name, or email address')
        user_id = user_id[5:] if user_id and user_id.startswith('guid:') else user_id
        results = GsUsersApi.get_users(user_ids=[user_id] if user_id else None,
                                       user_names=[name] if name else None,
                                       user_emails=[email] if email else None)
        if len(results) > 1:
            raise MqValueError('Error: This request resolves to more than one user in Marquee')
        if len(results) == 0:
            raise MqValueError('Error: No user found')
        return User(user_id=results[0].id,
                    name=results[0].name,
                    email=results[0].email,
                    company=results[0].company)

    @classmethod
    def get_many(cls,
                 user_ids: List[str] = None,
                 names: List[str] = None,
                 emails: List[str] = None,
                 companies: List[str] = None):
        """
        Resolve requested parameters into a list of User objects

        :param user_ids: User's unique GS Marquee User IDs
        :param names: User's names (formatted 'Last Name, First Name')
        :param emails: User's email addresses
        :param companies: User's companies
        :return: A list of User objects that corresponds to requested parameters
        """
        user_ids = user_ids if user_ids else []
        names = names if names else []
        emails = emails if emails else []
        companies = companies if companies else []

        if not user_ids + names + emails + companies:
            return []
        user_ids = [id_[5:] if id_.startswith('guid:') else id_ for id_ in user_ids]
        results = GsUsersApi.get_users(user_ids=user_ids,
                                       user_names=names,
                                       user_emails=emails,
                                       user_companies=companies)

        all_users = []
        for user in results:
            all_users.append(User(user_id=user.id,
                                  name=user.name,
                                  email=user.email,
                                  company=user.company))
        return all_users

    def save(self):
        raise NotImplementedError


class Group:
    def __init__(self,
                 group_id: str,
                 name: str,
                 entitlements=None,
                 description: str = None,
                 tags: List = None):
        self.__id = group_id
        self.__name = name
        self.__entitlements = entitlements
        self.__description = description
        self.__tags = tags

    def __eq__(self, other):
        return self.id == other.id

    def __hash__(self):
        return hash(self.id) ^ hash(self.name)

    @property
    def id(self):
        return self.__id

    @property
    def name(self):
        return self.__name

    @name.setter
    def name(self, value: str):
        self.__name = value

    @property
    def entitlements(self):
        return self.__entitlements

    @entitlements.setter
    def entitlements(self, value):
        self.__entitlements = value

    @property
    def description(self):
        return self.__description

    @description.setter
    def description(self, value: str):
        self.__description = value

    @property
    def tags(self):
        return self.__tags

    @tags.setter
    def tags(self, value: List):
        self.__tags = value

    @classmethod
    def get(cls,
            group_id: str):
        """
        Resolve a group ID into a single Group object

        :param group_id: Group's unique GS Marquee ID
        :return: A Group object that corresponds to requested ID
        """
        group_id = group_id[6:] if group_id and group_id.startswith('group:') else group_id
        result = GsGroupsApi.get_group(group_id=group_id)
        return Group(group_id=result.id,
                     name=result.name,
                     entitlements=Entitlements.from_target(result.entitlements) if result.entitlements else None
                     if result.entitlements else None,
                     description=result.description,
                     tags=result.tags)

    @classmethod
    def get_many(cls,
                 group_ids: List[str] = None,
                 names: List[str] = None):
        """
        Resolve requested parameters into a list of Group objects

        :param group_ids: Group's unique GS Marquee IDs
        :param names: Group's names
        :return: A list of Group objects that corresponds to requested parameters
        """
        group_ids = group_ids if group_ids else []
        names = names if names else []
        if not group_ids + names:
            return []
        group_ids = [id_[6:] if id_.startswith('group:') else id_ for id_ in group_ids]
        results = GsGroupsApi.get_groups(ids=group_ids,
                                         names=names)
        all_groups = []
        for group in results:
            all_groups.append(Group(group_id=group.id,
                                    name=group.name,
                                    entitlements=Entitlements.from_target(group.entitlements)
                                    if group.entitlements else None,
                                    description=group.description,
                                    tags=group.tags)
                              )
        return all_groups

    def save(self):
        """
        If the group id already exists in Marquee, update it. If not, create a new Marquee Group
        """
        if self._group_exists():
            _logger.info(f'Updating group "{self.id}"')
            result = GsGroupsApi.update_group(group_id=self.id, group=self.to_target())
        else:
            _logger.info(f'Creating group "{self.id}"')
            result = GsGroupsApi.create_group(group=self.to_target())
        return Group(group_id=result.id,
                     name=result.name,
                     entitlements=Entitlements.from_target(result.entitlements) if result.entitlements else None
                     if result.entitlements else None,
                     description=result.description,
                     tags=result.tags)

    def _group_exists(self):
        try:
            Group.get(self.id)
            return True
        except MqRequestError as e:
            if e.status == 404:
                return False
            else:
                raise e

    def delete(self):
        """
        Delete this group from Marquee
        """
        GsGroupsApi.delete_group(self.id)
        _logger.info(f'Group "{self.id}" deleted from Marquee.')

    def get_users(self) -> List[User]:
        """
        Get a list of all users in this group
        """
        users = GsGroupsApi.get_users_in_group(self.id)
        return [User(user_id=user.get('id'),
                     name=user.get('name'),
                     email=user.get('email'),
                     company=user.get('company')) for user in users]

    def add_users(self,
                  users: List[User]):
        """
        Add a list of users to a group
        :param users: List of User objects
        """
        user_ids = [user.id for user in users]
        GsGroupsApi.add_users_to_group(group_id=self.id,
                                       user_ids=user_ids)
        _logger.info(f'Users added to "{self.name}".')

    def delete_users(self,
                     users: List[User]):
        """
        Remove a list of users to a group
        :param users: List of User objects
        """
        user_ids = [user.id for user in users]
        GsGroupsApi.delete_users_from_group(group_id=self.id,
                                            user_ids=user_ids)
        _logger.info(f'Users removed from "{self.name}".')

    def to_dict(self):
        """
        Return a Group object as a dictionary
        """
        return {
            'name': self.name,
            'id': self.id,
            'description': self.description,
            'entitlements': self.entitlements.to_dict() if self.entitlements else None,
            'tags': self.tags
        }

    def to_target(self):
        """
        Return a Group object as a target object
        """
        return TargetGroup(name=self.name,
                           id=self.id,
                           description=self.description,
                           entitlements=self.entitlements.to_target() if self.entitlements else None,
                           tags=self.tags)


class EntitlementBlock:
    def __init__(self,
                 users: List[User] = None,
                 groups: List[Group] = None,
                 roles: List[str] = None):
        self.__users = list(set(users)) if users else []
        self.__groups = list(set(groups)) if groups else []
        self.__roles = list(set(roles)) if roles else []

    @property
    def users(self):
        return self.__users

    @users.setter
    def users(self, value: List[User]):
        self.__users = list(set(value))

    @property
    def groups(self):
        return self.__groups

    @groups.setter
    def groups(self, value: List[Group]):
        self.__groups = list(set(value))

    @property
    def roles(self):
        return self.__roles

    @roles.setter
    def roles(self, value: List[str]):
        self.__roles = list(set(value))

    def is_empty(self):
        return len(self.users + self.groups + self.roles) == 0

    def to_list(self):
        return [f'guid:{user.id}' for user in self.users] + \
               [f'group:{group.id}' for group in self.groups] + \
               [f'role:{role}' for role in self.roles]


class Entitlements:
    def __init__(self,
                 admin: EntitlementBlock = None,
                 delete: EntitlementBlock = None,
                 display: EntitlementBlock = None,
                 edit: EntitlementBlock = None,
                 execute: EntitlementBlock = None,
                 plot: EntitlementBlock = None,
                 query: EntitlementBlock = None,
                 rebalance: EntitlementBlock = None,
                 trade: EntitlementBlock = None,
                 view: EntitlementBlock = None):
        self.__admin = admin if admin else EntitlementBlock()
        self.__delete = delete if delete else EntitlementBlock()
        self.__display = display if display else EntitlementBlock()
        self.__edit = edit if edit else EntitlementBlock()
        self.__execute = execute if execute else EntitlementBlock()
        self.__plot = plot if plot else EntitlementBlock()
        self.__query = query if query else EntitlementBlock()
        self.__rebalance = rebalance if rebalance else EntitlementBlock()
        self.__trade = trade if trade else EntitlementBlock()
        self.__view = view if view else EntitlementBlock()

    @property
    def admin(self):
        return self.__admin

    @admin.setter
    def admin(self, value: EntitlementBlock):
        self.__admin = value

    @property
    def delete(self):
        return self.__delete

    @delete.setter
    def delete(self, value: EntitlementBlock):
        self.__delete = value

    @property
    def display(self):
        return self.__display

    @display.setter
    def display(self, value: EntitlementBlock):
        self.__display = value

    @property
    def edit(self):
        return self.__edit

    @edit.setter
    def edit(self, value: EntitlementBlock):
        self.__edit = value

    @property
    def execute(self):
        return self.__execute

    @execute.setter
    def execute(self, value: EntitlementBlock):
        self.__execute = value

    @property
    def plot(self):
        return self.__plot

    @plot.setter
    def plot(self, value: EntitlementBlock):
        self.__plot = value

    @property
    def query(self):
        return self.__query

    @query.setter
    def query(self, value: EntitlementBlock):
        self.__query = value

    @property
    def rebalance(self):
        return self.__rebalance

    @rebalance.setter
    def rebalance(self, value: EntitlementBlock):
        self.__rebalance = value

    @property
    def trade(self):
        return self.__trade

    @trade.setter
    def trade(self, value: EntitlementBlock):
        self.__trade = value

    @property
    def view(self):
        return self.__view

    @view.setter
    def view(self, value: EntitlementBlock):
        self.__view = value

    def to_target(self) -> TargetEntitlements:
        """
        Return Entitlement object as a target object
        :return: Entitlements as a target object
        """
        return TargetEntitlements(
            admin=self.admin.to_list() if not self.admin.is_empty() else None,
            delete=self.delete.to_list() if not self.delete.is_empty() else None,
            display=self.display.to_list() if not self.display.is_empty() else None,
            edit=self.edit.to_list() if not self.edit.is_empty() else None,
            execute=self.execute.to_list() if not self.execute.is_empty() else None,
            plot=self.plot.to_list() if not self.plot.is_empty() else None,
            query=self.query.to_list() if not self.query.is_empty() else None,
            rebalance=self.rebalance.to_list() if not self.rebalance.is_empty() else None,
            trade=self.trade.to_list() if not self.trade.is_empty() else None,
            view=self.view.to_list() if not self.view.is_empty() else None
        )

    def to_dict(self) -> Dict:
        """
        Return Entitlement object as a dictionary
        :return: Entitlements as a dictionary
        """
        return self.to_target().as_dict()

    @classmethod
    def from_target(cls, entitlements: TargetEntitlements):
        """
        Create an Entitlement object from a target object
        :param entitlements: Entitlements as a target object
        :return: A new Entitlements object with all specified entitlements
        """
        return cls.from_dict(entitlements.to_json())

    @classmethod
    def from_dict(cls, entitlements: Dict):
        """
        Create an Entitlement object from a dictionary object
        :param entitlements: Entitlements as a dictionary object
        :return: A new Entitlements object with all specified entitlements
        """
        entitlement_kwargs = {}
        for action_info in entitlements:
            users, groups, roles = [], [], []
            for user in entitlements[action_info]:
                if user.startswith('guid:'):
                    users.append(user)
                elif user.startswith('group:'):
                    groups.append(user)
                elif user.startswith('role:'):
                    roles.append(user[5:])
            if users or groups or roles:
                entitlement_kwargs[action_info] = EntitlementBlock(
                    users=User.get_many(user_ids=users),
                    groups=Group.get_many(group_ids=groups),
                    roles=roles)
        return Entitlements(**entitlement_kwargs)
