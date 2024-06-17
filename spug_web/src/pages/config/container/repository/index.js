/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useEffect} from 'react';
import { observer } from 'mobx-react';
import { AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import store from './store';
import envStore from 'pages/config/environment/store';

export default observer(function () {

  useEffect(() => {
    envStore.fetchRecords()
  }, [])

  return (
    <AuthDiv auth="config.container.repository.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>配置中心</Breadcrumb.Item>
        <Breadcrumb.Item>容器仓库</Breadcrumb.Item>
      </Breadcrumb>
      <ComTable/>
      {store.formVisible && <ComForm/>}
    </AuthDiv>
  )
})
