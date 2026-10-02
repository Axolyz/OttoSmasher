import React from 'react';
import {Alert,Button} from 'antd';
export default class ViewBoundary extends React.Component<{children:React.ReactNode},{error:string;revision:number}> {
  state={error:'',revision:0};
  static getDerivedStateFromError(error:Error){return {error:error.message}}
  componentDidCatch(error:Error,info:React.ErrorInfo){console.error('OTTO_DIAGNOSTIC '+JSON.stringify({event:'panel-error',message:error.message,stack:info.componentStack}))}
  render(){return this.state.error?<Alert type='error' message='此面板未能显示' description={this.state.error} action={<Button onClick={()=>this.setState({error:'',revision:this.state.revision+1})}>重新打开面板</Button>}/>:<React.Fragment key={this.state.revision}>{this.props.children}</React.Fragment>}
}
