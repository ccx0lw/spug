/**
 * Copyright: (c) ccx0lw. https://github.com/ccx0lw/spug
 * Copyright: (c) <fcjava@163.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Input, Select, Form } from 'antd';


function Render(props) {
  switch (props.type) {
    case 'string':
      return <Input value={props.value} onChange={props.onChange} placeholder="请输入"/>
    case 'password':
      return <Input.Password value={props.value} onChange={props.onChange} placeholder="请输入"/>
    case 'select':
      const options = props.options.split('\n').map(x => x.split(':'))
      return (
        <Select value={props.value} onChange={props.onChange} placeholder="请选择">
          {options.map((item, index) => item.length > 1 ? (
            <Select.Option key={index} value={item[0]}>{item[1]}</Select.Option>
          ) : (
            <Select.Option key={index} value={item[0]}>{item[0]}</Select.Option>
          ))}
        </Select>
      )
    default:
      return null
  }
}

export default function Parameter(props) {
  // const [form] = Form.useForm();

  // function handleSubmit() {
  //   const formData = form.getFieldsValue();
  //   for (let item of props.parameters.filter(x => x.required)) {
  //     if (!formData[item.variable]) {
  //       return message.error(`${item.name} 是必填项。`)
  //     }
  //   }
  //   props.onOk(formData);
  //   props.onCancel()
  // }

  return (
    <div>
      {props.parameters.length === 0 ? (<span style={{ display: 'block', textAlign: 'center' }}>无</span>) : null}
      {props.parameters.map(item => (
            <Form.Item required={item.required} key={item.variable} name={item.variable} label={item.name}
                        tooltip={item.desc} initialValue={item.default}>
              <Render type={item.type} options={item.options}/>
            </Form.Item>
          ))}
    </div>
  )
}